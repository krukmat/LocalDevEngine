import sys
import asyncio
import json
import logging
import os
from typing import List, Optional

# Re-importamos las dependencias internas (la estructura depende de dónde ejecutes el script)
try:
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    from core.orchestrator import Orchestrator
    from core.ingestor import DataIngestor
    from models.base import ModelCallError
    from prompts.specialized_prompts import PromptRegistry
    import yaml
except ImportError as e:
    print(f"❌ Error de ruta o carga: {e}")
    sys.exit(1)

# Exit codes (docs/plan-receipt-interface-callers.md #7): the CLI is meant to be
# consumed by a subprocess caller (e.g. fenix's delegate-low-rri.py), which needs
# a machine-checkable signal that a receipt exists — not what the receipt says.
# qa_approved/deviation are policy decisions for the CALLER to make by reading the
# receipt; encoding them into the exit code would force the engine to change every
# time a caller's acceptance threshold changes.
EXIT_OK = 0        # pipeline ran to completion (or fast path) and produced a receipt
EXIT_ENGINE_FAIL = 2   # engine failed mid-run (partial receipt) or hit max_run_seconds
EXIT_USAGE = 3      # bad invocation (unknown command, missing/extra args, bad flags)

# main.py is the application entry point, so it's the one place allowed to configure
# logging handlers/levels. core/orchestrator.py only emits to its module logger and
# never touches this — a caller embedding Orchestrator as a library keeps full control.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s [%(message)s]",
)

# --- Estética básica para Terminal (Colores ANSI) ---
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

class DevOrchestratorCLI:
    """
    Interactive and Command Line Interface for the Dev Orchestrator.
    Implements a REPL mode for continuous conversation.
    """

    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.orchestrator = Orchestrator(config_path)

    async def ingest(self, directory: str):
        """Index a directory to build the local knowledge base."""
        ingestion_cfg = self.config.get('ingestion', {})
        embeddings_cfg = self.config.get('embeddings', {})
        ingestor = DataIngestor(
            self.orchestrator.memory,
            self.orchestrator.embedder,
            extensions=ingestion_cfg.get('extensions'),
            ignored_dirs=set(ingestion_cfg.get('ignored_dirs', [])) or None,
            max_file_bytes=ingestion_cfg.get('max_file_bytes', 1_000_000),
            max_chunk_chars=embeddings_cfg.get('max_chunk_chars', 3000),
            batch_size=embeddings_cfg.get('batch_size', 16),
        )
        await ingestor.ingest_directory(directory)

    def _print_result(self, result: dict, streamed: bool = False):
        """Displays a run_complex_task result, handling both the Router fast path and the
        full pipeline. When streamed=True, plan/implementation text was already printed
        live via _on_chunk as it generated, so only the summary banners are shown here —
        printing them again would duplicate the whole response."""
        status = result.get("status", "completed")
        if status != "completed":
            error = result.get("error") or {}
            print(f"{Colors.RED}--- PIPELINE {status.upper()} ---{Colors.ENDC}")
            if error.get("message"):
                print(f"{Colors.RED}{error.get('stage', '?')}: {error['message']}{Colors.ENDC}")
            return

        if result.get("fast_path"):
            if not streamed:
                print(f"\n{Colors.GREEN}--- RESPUESTA RÁPIDA (Router) ---{Colors.ENDC}\n{result['implementation']}")
            return

        if not streamed:
            print(f"\n{Colors.GREEN}--- PLAN DEL ARQUITECTO ---{Colors.ENDC}\n{result['plan']}")
            print(f"{Colors.BLUE}--- IMPLEMENTACIÓN SENIOR ---{Colors.ENDC}\n{result['implementation']}")

        if result.get("qa_approved"):
            print(f"{Colors.GREEN}--- QA: APROBADO ---{Colors.ENDC}")
        else:
            max_iter = self.orchestrator.config.get('pipeline', {}).get('max_qa_iterations', 2)
            print(f"{Colors.YELLOW}--- QA: NO APROBADO TRAS {max_iter} REINTENTOS ---{Colors.ENDC}")
            if result.get("qa_feedback"):
                print(result["qa_feedback"])

        deviation = result.get("deviation")
        if deviation is not None:
            deviation_colors = {
                "NONE": Colors.GREEN,
                "JUSTIFIED": Colors.CYAN,
                "UNEXPLAINED": Colors.YELLOW,
                "UNKNOWN": Colors.YELLOW,
            }
            color = deviation_colors.get(deviation, Colors.YELLOW)
            print(f"{color}--- REPORTE DE CIERRE: DEVIATION={deviation} ---{Colors.ENDC}")
            if not streamed and result.get("closing_report"):
                print(result["closing_report"])

    def _make_stage_printer(self, file=None):
        """Builds an on_chunk callback that prints a stage header (colored, once) the
        first time each stage streams, then streams its text live. Stages repeat across
        revision attempts (e.g. design_revision may run 0-2 times), so headers must be
        keyed by (stage, attempt), not by stage alone.

        file defaults to stdout; --json mode passes sys.stderr so stdout stays pure
        JSON (docs/plan-receipt-interface-callers.md, "B. El transporte")."""
        stream = file if file is not None else sys.stdout
        seen_headers = set()
        current = {"key": None}
        labels = {
            "fast_path": (Colors.GREEN, "RESPUESTA RÁPIDA (Router)"),
            "design_plan": (Colors.GREEN, "PLAN DEL ARQUITECTO"),
            "design_revision": (Colors.YELLOW, "REVISIÓN DEL PLAN"),
            "implementation": (Colors.BLUE, "IMPLEMENTACIÓN SENIOR"),
            "closing_report": (Colors.CYAN, "REPORTE DE CIERRE (Manager)"),
        }

        def on_chunk(text: str, stage: str, attempt: Optional[int]):
            key = (stage, attempt)
            if key != current["key"]:
                current["key"] = key
                color, label = labels.get(stage, (Colors.CYAN, stage.upper()))
                if key not in seen_headers:
                    seen_headers.add(key)
                    print(f"\n{color}--- {label} ---{Colors.ENDC}", file=stream)
            print(text, end="", flush=True, file=stream)

        return on_chunk

    async def ask_once(
        self,
        query: str,
        as_json: bool = False,
        out_path: Optional[str] = None,
        quiet: bool = False,
        output_contract: Optional[str] = None,
    ) -> int:
        """Executes a single inquiry and exits. Never prompts — the macro-loop re-run
        offered after a closing report is a `chat`-only feature (see _maybe_offer_macro_rerun):
        `ask` is the scriptable, non-interactive path and must not block on input().

        Returns the process exit code (see EXIT_* constants) instead of exiting directly,
        so main() stays the single place that calls sys.exit.

        Transport (docs/plan-receipt-interface-callers.md, "B. El transporte"):
        - as_json: the model stream goes to stderr, stdout is JSON-only (the receipt),
          so a subprocess caller can json.loads(stdout) without stripping ANSI or
          parsing Spanish headers.
        - out_path: the receipt is written to this file instead of stdout; stdout stays
          the human-readable stream.
        - quiet: disables on_chunk entirely (no live stream at all).
        - output_contract: forwarded to run_complex_task (see PromptRegistry.OUTPUT_CONTRACTS).
        """
        stream_target = sys.stderr if as_json else sys.stdout
        on_chunk = None if quiet else self._make_stage_printer(file=stream_target)
        try:
            result = await self.orchestrator.run_complex_task(
                query, on_chunk=on_chunk, output_contract=output_contract
            )
        except ModelCallError as e:
            # Defensive: run_complex_task already catches ModelCallError internally and
            # returns a "failed" receipt. This remains as a backstop in case a caller of
            # a future version raises before that wrapping, so a raw exception can never
            # bypass the JSON/exit-code contract.
            print(f"{Colors.RED}❌ Fallo llamando al modelo: {e}{Colors.ENDC}", file=stream_target)
            return EXIT_ENGINE_FAIL

        if not quiet:
            print(file=stream_target)  # close the last streamed line before the summary banners

        if as_json or out_path:
            payload = json.dumps(result, ensure_ascii=False, indent=2)
            if out_path:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(payload)
                if not quiet:
                    print(f"{Colors.CYAN}(Recibo guardado en {out_path}){Colors.ENDC}", file=sys.stdout)
            else:
                print(payload)  # stdout stays JSON-only; streamed text went to stderr above
        else:
            self._print_result(result, streamed=True)
            if self._macro_rerun_available(result):
                print(f"{Colors.CYAN}(Re-ejecución con el reporte de cierre como feedback disponible en 'python main.py chat'){Colors.ENDC}")

        status = result.get("status", "completed")
        if status == "completed":
            return EXIT_OK
        return EXIT_ENGINE_FAIL  # "failed" or "timeout" — still a real receipt, just not a clean run

    def _macro_rerun_available(self, result: dict) -> bool:
        """True if this result's deviation/QA state would make a macro-loop re-run
        worth offering — an UNEXPLAINED/UNKNOWN closing report, or QA giving up after
        max_qa_iterations. Shared between ask_once (informational only) and
        interactive_shell (actually offers the prompt), so the two paths can't drift
        on what counts as 'worth re-running'."""
        if result.get("fast_path"):
            return False
        deviation = result.get("deviation")
        qa_approved = result.get("qa_approved")
        return deviation in ("UNEXPLAINED", "UNKNOWN") or qa_approved is False

    async def _maybe_offer_macro_rerun(self, query: str, result: dict) -> dict:
        """After printing a full-pipeline result in `chat`, offers one human-confirmed
        re-run of the whole pipeline if the closing report found something actionable
        (see docs/plan-macro-loop-manager-hitl.md, FASE 2). Default is NO — an empty
        Enter must decline, since the cost being confirmed is a full ~8-11 minute pipeline
        pass, not a cheap retry. Returns the possibly-updated result (the re-run's result
        if the user accepted, otherwise the original)."""
        if not self._macro_rerun_available(result):
            return result
        max_macro_iterations = self.orchestrator.config.get('pipeline', {}).get('max_macro_iterations', 1)
        macro_iteration = result.get("macro_iteration", 1)
        if macro_iteration > max_macro_iterations:
            return result

        answer = input(
            f"{Colors.YELLOW}⟳ El Manager detectó desvío sin explicar (o QA no aprobó). "
            f"¿Re-ejecutar con este reporte como feedback?\n"
            f"  (otra vuelta completa del pipeline, ~8-11 min) [s/N]: {Colors.ENDC}"
        ).strip().lower()
        if answer != "s":
            return result

        rerun_result = await self.orchestrator.run_complex_task(
            query,
            on_chunk=self._make_stage_printer(),
            prior_breakdown=result.get("breakdown"),
            prior_report=result.get("closing_report"),
            macro_iteration=macro_iteration + 1,
        )
        print()
        self._print_result(rerun_result, streamed=True)
        return rerun_result

    async def interactive_shell(self):
        """The REPL (Read-Eval-Print Loop) mode for deep work sessions."""
        print(f"\n{Colors.HEADER}{Colors.BOLD}=== DEV-ORCHESTRATOR INTERACTIVE SESSION ==={Colors.ENDC}")
        print(f"{Colors.BLUE}Escribe 'exit' o 'quit' para salir.{Colors.ENDC}")
        print(f"{Colors.CYAN}Comandos: 'help', 'status', 'clear'{Colors.ENDC}\n")

        while True:
            try:
                # Prompt estilizado
                user_input = input(f"{Colors.GREEN}➜ {Colors.ENDC}")
                if not user_input.strip():
                    continue
                
                cmd = user_input.lower().strip()

                if cmd in ["exit", "quit"]:
                    print(f"{Colors.YELLOW}Saliendo de la sesión...{Colors.ENDC}\n")
                    break
                elif cmd == "help":
                    print(f"\n{Colors.BOLD}Comandos disponibles:{Colors.ENDC}")
                    print("  ask <pregunta> - Lanza el pipeline completo.")
                    print("  status        - Muestra qué componentes están listos.")
                    print("  clear         - Limpia la pantalla del terminal.")
                    print("  exit          - Sale de la sesión.\n")
                elif cmd == "status":
                    print(f"{Colors.CYAN}Modelo Manager:{Colors.ENDC} {self.orchestrator.config['roles']['manager']['model_name']}")
                    print(f"{Colors.CYAN}Motor RAG:{Colors.ENDC} Activo (Nomic)")
                elif cmd == "clear":
                    os.system('cls' if os.name == 'nt' else 'clear')
                else:
                    # Si el usuario solo mete texto, lo trata como una pregunta directa al pipeline
                    result = await self.orchestrator.run_complex_task(user_input, on_chunk=self._make_stage_printer())
                    print()
                    self._print_result(result, streamed=True)
                    await self._maybe_offer_macro_rerun(user_input, result)

            except KeyboardInterrupt:
                print("\n\nInterrupción detectada. Saliendo...")
                break
            except Exception as e:
                print(f"{Colors.RED}❌ Error en la sesión: {e}{Colors.ENDC}")

def _parse_ask_args(argv: List[str]):
    """Parses `ask` flags/positional query. Returns (options_dict, error_message).
    error_message is set (and options_dict is None) on bad usage — e.g. an unknown
    flag or extra positional args — per docs/plan-receipt-interface-callers.md #15:
    unrecognized input must fail with EXIT_USAGE, not be silently ignored."""
    opts = {
        "query": None, "as_json": False, "out_path": None, "quiet": False,
        "output_contract": None, "input_file": None,
    }
    i = 0
    positional: List[str] = []
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            opts["as_json"] = True
        elif arg == "--quiet":
            opts["quiet"] = True
        elif arg == "--out":
            if i + 1 >= len(argv):
                return None, "--out requiere un valor (ruta de archivo)."
            i += 1
            opts["out_path"] = argv[i]
        elif arg == "--input-file":
            if i + 1 >= len(argv):
                return None, "--input-file requiere un valor (ruta de archivo)."
            i += 1
            opts["input_file"] = argv[i]
        elif arg == "--output-contract":
            if i + 1 >= len(argv):
                return None, "--output-contract requiere un valor."
            i += 1
            value = argv[i]
            if value not in PromptRegistry.OUTPUT_CONTRACTS:
                return None, (
                    f"--output-contract desconocido: {value!r}. "
                    f"Valores válidos: {', '.join(PromptRegistry.OUTPUT_CONTRACTS)}."
                )
            opts["output_contract"] = value
        elif arg.startswith("--"):
            return None, f"Flag desconocida: {arg}"
        else:
            positional.append(arg)
        i += 1

    if opts["input_file"] and positional:
        return None, "No pases una query posicional junto con --input-file."
    if len(positional) > 1:
        return None, f"Argumentos extra no reconocidos: {positional[1:]}"

    if opts["input_file"]:
        try:
            with open(opts["input_file"], "r", encoding="utf-8") as f:
                opts["query"] = f.read()
        except OSError as e:
            return None, f"No se pudo leer --input-file: {e}"
    elif positional:
        opts["query"] = positional[0]
    elif not sys.stdin.isatty():
        opts["query"] = sys.stdin.read()

    if not opts["query"] or not opts["query"].strip() or opts["query"] == '""':
        return None, "Debes proporcionar una pregunta (posicional, --input-file, o stdin)."
    return opts, None


async def main() -> int:
    if len(sys.argv) < 2:
        print(f"{Colors.YELLOW}Uso:{Colors.ENDC}")
        print("  python main.py ingest <directory_path>              # Indexar proyecto")
        print("  python main.py ask [flags] <\"query\">                # Pregunta rápida (Pipeline)")
        print("      --json                  Stdout es JSON puro (el stream va a stderr)")
        print("      --out FILE              Escribe el recibo a FILE en vez de stdout")
        print("      --quiet                 No streamea texto en vivo")
        print("      --input-file FILE       Lee la query desde FILE en vez de argv")
        print("      (si no hay query posicional ni --input-file, lee de stdin)")
        print(f"      --output-contract X     Uno de: {', '.join(PromptRegistry.OUTPUT_CONTRACTS)}")
        print("  python main.py chat                                 # Modo interactivo (REPL)")
        return EXIT_USAGE

    config_path = "config/settings.yaml"
    cli = DevOrchestratorCLI(config_path)
    command = sys.argv[1]
    exit_code = EXIT_OK

    try:
        if command == "ingest":
            if len(sys.argv) < 3:
                print("Error: Debes especificar una ruta para indexar.")
                return EXIT_USAGE
            await cli.ingest(sys.argv[2])
        elif command == "ask":
            opts, error = _parse_ask_args(sys.argv[2:])
            if error:
                print(f"{Colors.RED}Error: {error}{Colors.ENDC}", file=sys.stderr)
                return EXIT_USAGE
            exit_code = await cli.ask_once(
                opts["query"], as_json=opts["as_json"], out_path=opts["out_path"],
                quiet=opts["quiet"], output_contract=opts["output_contract"],
            )
        elif command == "chat":
            await cli.interactive_shell()
        else:
            print(f"Comando desconocido: {command}")
            return EXIT_USAGE
    finally:
        await cli.orchestrator.aclose()

    return exit_code

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
