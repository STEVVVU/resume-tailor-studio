from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class WorkflowAgent:
    name: str
    step_text: str
    mode: Literal["json", "latex"]
    system_prompt: str


@dataclass
class PromptBundle:
    global_rules: str
    workflow_agents: list[WorkflowAgent]


def _clean_text(text: str) -> str:
    return text.replace("—", "-").replace("–", "-").replace("→", "->")


def _extract_section(text: str, start_label: str, end_label: str | None = None) -> str:
    start_idx = text.find(start_label)
    if start_idx < 0:
        return ""
    end_idx = text.find(end_label, start_idx) if end_label else -1
    if end_idx < 0:
        end_idx = len(text)
    return text[start_idx:end_idx].strip()


def _extract_workflow_steps(text: str) -> list[str]:
    workflow = _extract_section(text, "Workflow (when user provides JD + LaTeX)")
    if not workflow:
        return []
    steps: list[str] = []
    for line in workflow.splitlines():
        match = re.match(r"^\s*\d+\)\s*(.+?)\s*$", line)
        if match:
            steps.append(match.group(1))
    return steps


def extract_workflow_steps_from_text(text: str) -> list[str]:
    cleaned = _clean_text(text)
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    return _extract_workflow_steps(cleaned)


def _agent_from_step(idx: int, step_text: str) -> WorkflowAgent:
    lower = step_text.lower()
    if "analyze jd" in lower:
        return WorkflowAgent(
            name=f"Agent {idx}: JD Analyst",
            step_text=step_text,
            mode="json",
            system_prompt=(
                "Extract required/preferred stack, responsibilities, keywords, and role signal. "
                "Return JSON keys: required_skills, preferred_skills, responsibilities, keywords, role_type."
            ),
        )
    if "assess adjacency" in lower:
        return WorkflowAgent(
            name=f"Agent {idx}: Adjacency Mapper",
            step_text=step_text,
            mode="json",
            system_prompt=(
                "Map JD keywords to credible resume adjacencies. "
                "Return JSON keys: strong_matches, weak_matches, avoid_forcing, transferable_focus."
            ),
        )
    if "plan edits" in lower:
        return WorkflowAgent(
            name=f"Agent {idx}: Edit Planner",
            step_text=step_text,
            mode="json",
            system_prompt=(
                "Create concrete edit plan before writing. "
                "Return JSON keys: bullet_strategy, skills_strategy, section_order, keyword_placement."
            ),
        )
    if "execute" in lower:
        return WorkflowAgent(
            name=f"Agent {idx}: Resume Tailor",
            step_text=step_text,
            mode="latex",
            system_prompt=(
                "Apply planned edits to produce FULL LaTeX resume. "
                "Respect locked sections and formatting constraints."
            ),
        )
    if "output" in lower:
        return WorkflowAgent(
            name=f"Agent {idx}: Compliance Guard",
            step_text=step_text,
            mode="latex",
            system_prompt=(
                "Validate and enforce all rules. "
                "Return FULL LaTeX only; fix violations if present."
            ),
        )
    return WorkflowAgent(
        name=f"Agent {idx}: Workflow Step",
        step_text=step_text,
        mode="json",
        system_prompt="Execute this workflow step faithfully and return concise JSON with decisions and outputs.",
    )


def build_prompt_bundle(instructions_path: Path) -> PromptBundle:
    raw = _clean_text(instructions_path.read_text(encoding="utf-8", errors="ignore"))
    raw = re.sub(r"\r\n?", "\n", raw)

    objectives = _extract_section(raw, "Core Objectives", "Translation-First Policy")
    translation = _extract_section(raw, "Translation-First Policy", "Bullet Styling Rules")
    bullets = _extract_section(raw, "Bullet Styling Rules", "Domain Alignment Strategy")
    skills = _extract_section(raw, "Technical Skills Section", "Global Anti-Density Rules")
    strict = _extract_section(raw, "STRICT RULES", "OUTPUT RULES")
    output = _extract_section(raw, "OUTPUT RULES", "Workflow")
    workflow_steps = _extract_workflow_steps(raw)

    global_rules = "\n\n".join(filter(None, [objectives, translation, bullets, skills, strict, output]))

    agents: list[WorkflowAgent] = []
    for idx, step_text in enumerate(workflow_steps, start=1):
        agents.append(_agent_from_step(idx, step_text))

    if not agents:
        agents = [
            WorkflowAgent(
                name="Agent 1: JD Analyst",
                step_text="Analyze JD",
                mode="json",
                system_prompt=(
                    "Extract required and preferred stack, responsibilities, and top keywords. "
                    "Return JSON keys: required_skills, preferred_skills, responsibilities, keywords, role_type."
                ),
            ),
            WorkflowAgent(
                name="Agent 2: Resume Tailor",
                step_text="Execute edits",
                mode="latex",
                system_prompt=(
                    "Produce FULL updated LaTeX resume only. "
                    "Apply translation-first edits and keep credibility."
                ),
            ),
            WorkflowAgent(
                name="Agent 3: Compliance Guard",
                step_text="Output final",
                mode="latex",
                system_prompt=(
                    "Verify all rules and return corrected FULL LaTeX only."
                ),
            ),
        ]

    return PromptBundle(
        global_rules=global_rules,
        workflow_agents=agents,
    )
