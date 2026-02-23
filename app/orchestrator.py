from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from .llm_client import LLMClient
from .prompt_splitter import PromptBundle, WorkflowAgent


@dataclass
class OrchestrationResult:
    latex: str
    jd_analysis: str


class ResumeOrchestrator:
    def __init__(self, llm: LLMClient, prompts: PromptBundle) -> None:
        self.llm = llm
        self.prompts = prompts

    def tailor(
        self,
        current_resume: str,
        job_description: str,
        api_key: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        progress_cb: Optional[Callable[[str, int, Optional[str]], None]] = None,
    ) -> OrchestrationResult:
        def update(stage: str, percent: int, jd_analysis: Optional[str] = None) -> None:
            if progress_cb:
                progress_cb(stage, percent, jd_analysis)

        update("Preparing orchestration", 5)
        if not self.llm.enabled and not api_key:
            disabled_msg = json.dumps(
                {
                    "status": "llm_disabled",
                    "message": "No API key available; returning cached resume unchanged.",
                },
                indent=2,
            )
            update("LLM disabled; returning cached resume", 100, disabled_msg)
            return OrchestrationResult(
                latex=current_resume,
                jd_analysis=disabled_msg,
            )

        agents = self.prompts.workflow_agents
        total = max(1, len(agents))
        jd_analysis = ""
        final_latex = current_resume
        artifacts: list[str] = []

        for idx, agent in enumerate(agents, start=1):
            start_pct = int(5 + ((idx - 1) / total) * 90)
            end_pct = int(5 + (idx / total) * 90)
            update(f"{agent.name}: running ({idx}/{total})", start_pct, jd_analysis or None)
            result = self.llm.complete(
                system_prompt=self._build_system_prompt(agent),
                user_prompt=self._build_user_prompt(
                    agent=agent,
                    current_resume=current_resume,
                    job_description=job_description,
                    artifacts=artifacts,
                ),
                api_key_override=api_key,
                provider_override=llm_provider,
                model_override=llm_model,
            )
            artifacts.append(f"{agent.name}\n{result}")

            if "jd analyst" in agent.name.lower() or "analyze jd" in agent.step_text.lower():
                jd_analysis = result
                update(f"{agent.name}: completed", end_pct, jd_analysis)
            else:
                update(f"{agent.name}: completed", end_pct, jd_analysis or None)

            if agent.mode == "latex":
                final_latex = result
                current_resume = result

        if not jd_analysis and artifacts:
            jd_analysis = artifacts[0]

        update("Completed", 100)
        return OrchestrationResult(latex=final_latex, jd_analysis=jd_analysis)

    def _build_system_prompt(self, agent: WorkflowAgent) -> str:
        return (
            f"{self.prompts.global_rules}\n\n"
            f"You are {agent.name}.\n"
            f"Workflow step: {agent.step_text}\n"
            f"{agent.system_prompt}"
        )

    def _build_user_prompt(
        self,
        agent: WorkflowAgent,
        current_resume: str,
        job_description: str,
        artifacts: list[str],
    ) -> str:
        prior = "\n\n".join(artifacts[-4:]) if artifacts else "None"
        mode_line = "Return ONLY valid JSON." if agent.mode == "json" else "Return ONLY full LaTeX resume code."
        return (
            f"{mode_line}\n\n"
            f"Job Description:\n{job_description}\n\n"
            f"Current Resume (LaTeX):\n{current_resume}\n\n"
            f"Prior Agent Outputs:\n{prior}\n"
        )
