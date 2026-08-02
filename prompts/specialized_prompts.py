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

    @staticmethod
    def get_architect_thinking_template(context: str, goal: str) -> str:
        """Provides a template for deep reasoning (Thinking Mode)."""
        return f"""CONTEXT FROM PROJECT:\n{context}\n\nGOAL:\n{goal}\n\nTASK FOR ARCHITECT:\nAnalyze the logic and provide a structural plan. 
Consider edge cases, error handling, and dependency impacts before providing a final design."""

    @staticmethod
    def get_implementer_task_template(plan: str, context: str) -> str:
        """Provides a template for pure implementation."""
        return f"""ARCHITECTURE PLAN:\n{plan}\n\nPROJECT CONTEXT:\n{context}\n\nTASK FOR IMPLEMENTER:\nImplement the code blocks described in the plan.
Ensure all imports are correct and follow existing coding styles."""

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
    def get_qa_review_template(context: str, goal: str, plan: str, implementation: str) -> str:
        """Post-implementation check: QA compares the implementation against the approved plan."""
        return f"""GOAL:\n{goal}\n\nAPPROVED PLAN:\n{plan}\n\nIMPLEMENTATION:\n{implementation}\n\nTASK FOR QA AUDITOR (IMPLEMENTATION CHECK):
Compare the implementation against the plan and the original goal. Flag any deviation, bug, missing
piece, or requirement that isn't satisfied.

Respond in EXACTLY this format:
VERDICT: APPROVED or NEEDS_REVISION
FEEDBACK: <specific, actionable feedback for the Architect/Implementer to address. If APPROVED, write "None".>"""

    @staticmethod
    def get_architect_revision_template(context: str, goal: str, previous_plan: str, feedback: str) -> str:
        """Feeds QA feedback back into the Architect to revise the plan (the design feedback loop)."""
        return f"""GOAL:\n{goal}\n\nPROJECT CONTEXT:\n{context}\n\nPREVIOUS PLAN:\n{previous_plan}\n\nQA FEEDBACK:\n{feedback}\n\nTASK FOR ARCHITECT:
Revise the plan to address the QA feedback above. Keep what already works; fix only what was flagged."""
