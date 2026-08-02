import sys
import asyncio
import logging
import os
from typing import List, Optional

# Re-importamos las dependencias internas (la estructura depende de dónde ejecutes el script)
try:
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    from core.orchestrator import Orchestrator
    from core.ingestor import DataIngestor
    from models.base import ModelCallError
    import yaml
except ImportError as e:
    print(f"❌ Error de ruta o carga: {e}")
    sys.exit(1)

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
        print(f"{Colors.CYAN}🚀 Iniciando indexación en:{Colors.ENDC} {directory}")
        from memory.embeddings import EmbeddingService
        from memory.local_memory import LocalVectorMemory

        # Re-inicializamos para asegurar que los paths de memoria sean correctos
        ingestor = DataIngestor(self.orchestrator.memory, self.orchestrator.embedder)
        await ingestor.ingest_directory(directory)

    def _print_result(self, result: dict):
        """Displays a run_complex_task result, handling both the Router fast path and the full pipeline."""
        if result.get("fast_path"):
            print(f"\n{Colors.GREEN}--- RESPUESTA RÁPIDA (Router) ---{Colors.ENDC}\n{result['implementation']}")
            return

        print(f"\n{Colors.GREEN}--- PLAN DEL ARQUITECTO ---{Colors.ENDC}\n{result['plan']}")
        print(f"{Colors.BLUE}--- IMPLEMENTACIÓN SENIOR ---{Colors.ENDC}\n{result['implementation']}")

        if result.get("qa_approved"):
            print(f"{Colors.GREEN}--- QA: APROBADO ---{Colors.ENDC}")
        else:
            max_iter = self.orchestrator.config.get('pipeline', {}).get('max_qa_iterations', 2)
            print(f"{Colors.YELLOW}--- QA: NO APROBADO TRAS {max_iter} REINTENTOS ---{Colors.ENDC}")
            if result.get("qa_feedback"):
                print(result["qa_feedback"])

    async def ask_once(self, query: str):
        """Executes a single inquiry and exits."""
        try:
            result = await self.orchestrator.run_complex_task(query)
            self._print_result(result)
        except ModelCallError as e:
            print(f"{Colors.RED}❌ Fallo llamando al modelo: {e}{Colors.ENDC}")

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
                    result = await self.orchestrator.run_complex_task(user_input)
                    self._print_result(result)

            except KeyboardInterrupt:
                print("\n\nInterrupción detectada. Saliendo...")
                break
            except Exception as e:
                print(f"{Colors.RED}❌ Error en la sesión: {e}{Colors.ENDC}")

async def main():
    if len(sys.argv) < 2:
        print(f"{Colors.YELLOW}Uso:{Colors.ENDC}")
        print("  python main.py ingest <directory_path>  # Indexar proyecto")
        print("  python main.py ask <\"query\">          # Pregunta rápida (Pipeline)")
        print("  python main.py chat                     # Modo interactivo (REPL)")
        return

    config_path = "config/settings.yaml"
    cli = DevOrchestratorCLI(config_path)
    command = sys.argv[1]

    if command == "ingest":
        if len(sys.argv) < 3:
            print("Error: Debes especificar una ruta para indexar.")
            return
        await cli.ingest(sys.argv[2])
    elif command == "ask":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        if not query or query == '""':
            print("Error: Debes proporcionar una pregunta.")
            return
        await cli.ask_once(query)
    elif command == "chat":
        await cli.interactive_shell()
    else:
        print(f"Comando desconocido: {command}")

if __name__ == "__main__":
    asyncio.run(main())
