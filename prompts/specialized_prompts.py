# prompts/specialized_prompts.py
from typing import Dict

class PromptRegistry:
    """
    Central repository for specialized system prompts 
    tailored to each role's strengths.
    """

    @staticmethod
    def get_system_prompt(role: str) -> str:
        """
        Returns the optimized system prompt for a specific role.
        The goal is to steer the model towards its intended behavior/strength.
        """
        prompts = {
            "router": (
                "You are a classification assistant. Analyze the user input and "
                "classify it into: [SIMPLE_TASK, COMPLEX_ARCHITECTURE, CODING_REQUEST, ERROR_REACTION]. "
                "Output ONLY the category name."
            ),
            "manager": (
                "You are an AI Project Manager. Your job is to coordinate tasks between "
                "an Architect and an Implementer. Breaking down high-level goals into "
                "step-by-step technical instructions. Use structured outlines."
            ),
            "architect": (
                "You are a Senior Software Architect. Focus on system design, data structures, "
                "and security patterns. Analyze the user's request and provide a high-level, "
                "logical blueprint for implementation. Prioritize scalability and clean code principles."
            ),
            "implementer": (
                "You are an Expert Senior Developer. Your task is to write production-ready, "
                "efficient, and bug-free code following the provided architectural plan. "
                "Do not explain too much; focus on providing high-quality implementation blocks."
            ),
            "copilot": (
                "You are an AI coding assistant specializing in real-time autocomplete. "
                "Suggest only the immediate next lines of code that complete the logic naturally."
            ),
            "qa_auditor": (
                "You are a meticulous, strict QA Auditor. Compare a proposed design or implementation "
                "against the original goal and plan. Identify concrete defects, gaps, or deviations. "
                "Approve only when the work genuinely satisfies the requirements — do not rubber-stamp. "
                "Always answer using the exact VERDICT/FEEDBACK format you are given in the task."
            )
        }
        return prompts.get(role, "You are a helpful coding assistant.")

    SECTION_NAMES = ("Data Model", "API/Interface", "Error Handling", "Dependencies/Integration")

    # Output contracts: an implementer/QA behavior that's opt-in per run (see
    # core/orchestrator.py's output_contract param, main.py's --output-contract).
    # "fenix-tagged-file" is the exact grammar fenix's delegate-low-rri.py parser
    # (STATUS/SUMMARY/=== FILE START ===/PATH/ACTION/--- CONTENT ---/=== FILE END ===)
    # already expects from a delegated model — copied verbatim from that script's own
    # system prompt (build_payload()) so the parser accepts LocalDevEngine's output
    # unmodified. See docs/plan-mitigation-fenix-outsourcing-controls.md, paso A3.
    OUTPUT_CONTRACTS = ("fenix-tagged-file",)

    _FENIX_TAGGED_FILE_GRAMMAR = """Return ONLY tagged text in this exact shape:
STATUS: PATCH
SUMMARY: short summary
TEST: optional verification command
RISK: optional risk note
=== FILE START ===
PATH: relative/path.ext
ACTION: create|modify|delete
--- CONTENT ---
<COMPLETE final file contents>
=== FILE END ===
Rules: use exactly one STATUS value: PATCH, NO_PATCH, or BLOCKED. Do not output the
pipe-separated list. No JSON, no markdown fences, no unified diff, no explanations, no
extra text outside these sections. For ACTION delete, emit empty content. Repeat the
=== FILE START === block once per file touched."""

    @staticmethod
    def _output_contract_suffix(output_contract: str = None) -> str:
        if output_contract == "fenix-tagged-file":
            return "\n\n" + PromptRegistry._FENIX_TAGGED_FILE_GRAMMAR
        return ""

    @staticmethod
    def get_architect_thinking_template(context: str, goal: str) -> str:
        """Provides a template for deep reasoning (Thinking Mode)."""
        section_headers = "\n".join(f"## {name}" for name in PromptRegistry.SECTION_NAMES)
        return f"""CONTEXT FROM PROJECT:\n{context}\n\nGOAL:\n{goal}\n\nTASK FOR ARCHITECT:\nAnalyze the logic and provide a structural plan.
Consider edge cases, error handling, and dependency impacts before providing a final design.

Structure your plan using EXACTLY these four section headers, in this order, each on its own line:
{section_headers}
Every section must be present even if brief (e.g. "N/A — no external dependencies."). Do not add,
remove, rename, or reorder sections — the headers are parsed verbatim by the review pipeline."""

    @staticmethod
    def get_implementer_task_template(plan: str, context: str, output_contract: str = None) -> str:
        """Provides a template for pure implementation. output_contract, if given, appends
        a grammar the Implementer must follow instead of free prose (see OUTPUT_CONTRACTS)."""
        return f"""ARCHITECTURE PLAN:\n{plan}\n\nPROJECT CONTEXT:\n{context}\n\nTASK FOR IMPLEMENTER:\nImplement the code blocks described in the plan.
Ensure all imports are correct and follow existing coding styles.{PromptRegistry._output_contract_suffix(output_contract)}"""

    @staticmethod
    def get_manager_breakdown_template(context: str, goal: str) -> str:
        """Manager turns a high-level goal into a short ordered outline that guides the Architect."""
        return f"""GOAL:\n{goal}\n\nPROJECT CONTEXT:\n{context}\n\nTASK FOR MANAGER:
Break this goal down into a short, ordered outline of the concrete steps needed to satisfy it.
Keep it high-level (no code), 3-7 bullet points, focused on what must happen and in what order."""

    @staticmethod
    def get_design_review_template(context: str, goal: str, plan: str) -> str:
        """Pre-implementation design gate: QA reviews the plan before any code is written."""
        return f"""GOAL:\n{goal}\n\nPROJECT CONTEXT:\n{context}\n\nPROPOSED PLAN:\n{plan}\n\nTASK FOR QA AUDITOR (DESIGN GATE):
Review this plan BEFORE any code is written. Check that it fully addresses the goal, accounts for
edge cases and dependency impacts, and doesn't introduce obvious architectural problems.

Respond in EXACTLY this format:
VERDICT: APPROVED or NEEDS_REVISION
FEEDBACK: <specific, actionable feedback for the Architect to address. If APPROVED, write "None".>"""

    @staticmethod
    def get_section_review_template(context: str, goal: str, section_name: str, section_text: str, full_plan: str) -> str:
        """Design gate, scoped to one plan section. The rest of the plan is included for
        cross-section consistency (e.g. the API section must match the Data Model section),
        but the verdict/feedback must be about section_name only — approving other sections
        or flagging issues outside this section belongs to their own review pass."""
        return f"""GOAL:\n{goal}\n\nPROJECT CONTEXT:\n{context}\n\nFULL PLAN (for cross-section consistency only):\n{full_plan}\n\nSECTION UNDER REVIEW — "{section_name}":\n{section_text}\n\nTASK FOR QA AUDITOR (DESIGN GATE — SINGLE SECTION):
Review ONLY the "{section_name}" section above BEFORE any code is written. Check that it fully
addresses its part of the goal, is consistent with the other sections shown, accounts for edge
cases, and doesn't introduce obvious architectural problems. Do not comment on other sections.

Respond in EXACTLY this format:
VERDICT: APPROVED or NEEDS_REVISION
FEEDBACK: <specific, actionable feedback for the Architect to address in THIS section only. If APPROVED, write "None".>"""

    @staticmethod
    def get_section_revision_template(context: str, goal: str, section_name: str, previous_section: str, feedback: str, full_plan: str) -> str:
        """Regenerates a single rejected section, keeping the rest of the plan as fixed
        context so the revision stays consistent with sections that already passed."""
        return f"""GOAL:\n{goal}\n\nPROJECT CONTEXT:\n{context}\n\nFULL PLAN (other sections are already approved — stay consistent with them):\n{full_plan}\n\nPREVIOUS "{section_name}" SECTION:\n{previous_section}\n\nQA FEEDBACK ON THIS SECTION:\n{feedback}\n\nTASK FOR ARCHITECT:
Revise ONLY the "{section_name}" section to address the QA feedback above. Output just the revised
section body — do not repeat the "## {section_name}" header, do not output other sections."""

    @staticmethod
    def get_qa_review_template(goal: str, plan: str, implementation: str, output_contract: str = None) -> str:
        """Post-implementation check: QA compares the implementation against the approved plan.
        When output_contract is set, grammar conformance becomes part of the verdict — an
        implementation a downstream parser can't consume must NOT be APPROVED just because
        its logic is otherwise correct (see docs/plan-mitigation-fenix-outsourcing-controls.md,
        paso A3 / fenix gap G11)."""
        contract_check = ""
        if output_contract == "fenix-tagged-file":
            contract_check = f"""

ADDITIONAL CHECK — OUTPUT CONTRACT CONFORMANCE (mandatory, checked BEFORE anything else):
The implementation above MUST follow this exact grammar, verbatim, with no extra text outside
its sections:
{PromptRegistry._FENIX_TAGGED_FILE_GRAMMAR}
If the implementation does not conform to this grammar exactly (wrong/missing markers, prose
outside sections, malformed STATUS/ACTION values, etc.), the verdict MUST be NEEDS_REVISION
regardless of whether the underlying code logic is otherwise correct — a grammar violation
alone is a defect."""
        return f"""GOAL:\n{goal}\n\nAPPROVED PLAN:\n{plan}\n\nIMPLEMENTATION:\n{implementation}\n\nTASK FOR QA AUDITOR (IMPLEMENTATION CHECK):
Compare the implementation against the plan and the original goal. Flag any deviation, bug, missing
piece, or requirement that isn't satisfied.{contract_check}

Respond in EXACTLY this format:
VERDICT: APPROVED or NEEDS_REVISION
FEEDBACK: <specific, actionable feedback for the Architect/Implementer to address. If APPROVED, write "None".>"""

    @staticmethod
    def get_architect_revision_template(context: str, goal: str, previous_plan: str, feedback: str) -> str:
        """Feeds QA feedback back into the Architect to revise the plan (the design feedback loop)."""
        return f"""GOAL:\n{goal}\n\nPROJECT CONTEXT:\n{context}\n\nPREVIOUS PLAN:\n{previous_plan}\n\nQA FEEDBACK:\n{feedback}\n\nTASK FOR ARCHITECT:
Revise the plan to address the QA feedback above. Keep what already works; fix only what was flagged."""

    @staticmethod
    def get_manager_closing_report_template(goal: str, breakdown: str, plan: str, implementation: str) -> str:
        """Closing report: Manager compares the final result against its own original outline.
        A step that was changed for a good reason (e.g. a QA-driven correction) is NOT a deviation —
        only unexplained gaps or unrequested additions are. This distinction is the whole point of the
        report: a naive aligned/deviated check would flag every legitimate correction as a problem."""
        return f"""ORIGINAL GOAL:\n{goal}\n\nYOUR ORIGINAL OUTLINE:\n{breakdown}\n\nFINAL APPROVED PLAN:\n{plan}\n\nFINAL IMPLEMENTATION:\n{implementation}\n\nTASK FOR MANAGER (CLOSING REPORT):
Compare the final plan and implementation against YOUR ORIGINAL OUTLINE above. For each step in your
outline, classify what happened to it:
- COVERED: the step was implemented as originally intended.
- ADAPTED: the step was implemented differently than outlined, but for a good reason (e.g. a QA
  finding, a technical constraint discovered during design). This is a legitimate correction, NOT a
  deviation — do not flag it as a problem.
- DROPPED: the step is missing from the final result with no explanation visible in the plan or code.
- ADDED: the final result includes something not in your original outline, with no clear justification.

List each outline step with its classification in one line. Then give an overall verdict: only DROPPED
or unjustified ADDED items count as a real deviation — COVERED and ADAPTED items do not.

Respond in EXACTLY this format:
DEVIATION: NONE or JUSTIFIED or UNEXPLAINED
SUMMARY: <2-4 sentences: what happened overall, and if UNEXPLAINED, exactly what was dropped or added
without justification.>"""
