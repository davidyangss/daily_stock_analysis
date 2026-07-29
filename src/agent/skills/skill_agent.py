# -*- coding: utf-8 -*-
"""
SkillAgent — runtime specialist adapter for a selected skill.

This is an optional multi-agent execution layer. The primary skill abstraction
in this repository is the instruction bundle loaded by :mod:`src.agent.skills.base`;
this adapter only exists for the orchestrator's specialist mode.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.evidence import canonical_tool_name
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.runner import try_parse_json
from src.agent.skills.defaults import build_skill_agent_name

logger = logging.getLogger(__name__)


class SkillAgent(BaseAgent):
    """Agent that evaluates a single trading skill for a stock."""

    # Built-in strategies can declare up to five hard evidence tools. Six
    # rounds allow sequential tool calls plus one final structured response;
    # providers that support parallel calls still normally finish sooner.
    max_steps = 6

    def __init__(self, skill_id: Optional[str] = None, strategy_id: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        resolved_skill_id = skill_id or strategy_id
        if not resolved_skill_id:
            raise ValueError("skill_id is required")
        self.skill_id = resolved_skill_id
        self.agent_name = build_skill_agent_name(resolved_skill_id)
        self._skill = self._load_skill(resolved_skill_id)

        if self._skill:
            tool_names = self._skill.required_tools
            if tool_names:
                self.tool_names = list(tool_names)

    @staticmethod
    def _load_skill(skill_id: str):
        """Load the Skill definition for a skill id."""
        try:
            from src.agent.factory import get_skill_manager

            sm = get_skill_manager()
            return sm.get(skill_id)
        except Exception as exc:
            logger.warning("[SkillAgent] failed to load skill '%s': %s", skill_id, exc)
        return None

    def system_prompt(self, ctx: AgentContext) -> str:
        if self._skill:
            instructions = self._skill.instructions or self._skill.description
            display = self._skill.display_name
        else:
            instructions = f"Evaluate the '{self.skill_id}' skill."
            display = self.skill_id

        required_tools = list(self._skill.required_tools) if self._skill else []
        required_tool_instruction = (
            "Required evidence tools: " + ", ".join(required_tools) + ". "
            "Call every required tool and do not claim a condition is verified when "
            "the tool returns missing/error/not_supported data."
            if required_tools
            else "No machine-readable required evidence tools are declared."
        )

        return f"""\
You are a **Skill Evaluation Agent** applying the **{display}** skill.

## Skill Instructions
{instructions}

## Task
Evaluate whether the current stock conditions satisfy this skill's entry
criteria. Use tools if needed to verify data points.

## Evidence Contract
{required_tool_instruction}
Record unavailable data in conditions_missed and lower confidence. Tool evidence
is validated by the runtime after your response.

## Output Format
Return **only** a JSON object:
{{
  "skill_id": "{self.skill_id}",
  "signal": "strong_buy|buy|hold|sell|strong_sell",
  "confidence": 0.0-1.0,
  "conditions_met": ["list of satisfied conditions"],
  "conditions_missed": ["list of unsatisfied conditions"],
  "score_adjustment": -20 to +20,
  "reasoning": "2-3 sentence skill evaluation"
}}
"""

    def attach_execution_evidence(
        self,
        opinion: AgentOpinion,
        tool_calls_log: List[Dict[str, Any]],
    ) -> AgentOpinion:
        opinion = super().attach_execution_evidence(opinion, tool_calls_log)
        required_tools = list(self._skill.required_tools) if self._skill else []
        if not required_tools:
            return opinion

        raw_data = dict(opinion.raw_data or {})
        all_evidence = [
            dict(item)
            for item in raw_data.get("tool_evidence", [])
            if isinstance(item, dict)
        ]
        status_rank = {
            "available": 0,
            "fallback": 1,
            "partial": 2,
            "estimated": 3,
            "stale": 4,
            "not_supported": 5,
            "missing": 6,
            "fetch_failed": 7,
        }
        required_evidence: List[Dict[str, Any]] = []
        missing_tools: List[str] = []
        limited_tools: List[str] = []
        for tool_name in required_tools:
            matching = [
                item
                for item in all_evidence
                if canonical_tool_name(item.get("tool")) == canonical_tool_name(tool_name)
            ]
            matching.sort(key=lambda item: status_rank.get(str(item.get("status")), 99))
            if matching:
                evidence = dict(matching[0])
            else:
                evidence = {
                    "tool": tool_name,
                    "status": "missing",
                    "sources": [],
                    "cached": False,
                    "partial": False,
                    "key_values": {},
                    "missing_reason": "required_tool_not_called",
                }
            evidence["required"] = True
            evidence["required_by"] = [self.skill_id]
            required_evidence.append(evidence)
            status = str(evidence.get("status") or "missing")
            if status in {"missing", "fetch_failed", "not_supported"}:
                missing_tools.append(tool_name)
            elif status in {"fallback", "partial", "estimated", "stale"}:
                limited_tools.append(tool_name)

        raw_data["required_tool_evidence"] = required_evidence
        raw_data["missing_required_tools"] = missing_tools
        raw_data["limited_required_tools"] = limited_tools
        raw_data["evidence_status"] = (
            "insufficient"
            if missing_tools
            else ("limited" if limited_tools else "verified")
        )
        opinion.raw_data = raw_data
        return opinion

    def build_user_message(self, ctx: AgentContext) -> str:
        parts = [
            f"Evaluate **{self.skill_id}** skill for stock "
            f"**{ctx.stock_code}** ({ctx.stock_name or 'unknown'}).",
        ]
        if ctx.opinions:
            for op in ctx.opinions:
                if op.agent_name == "technical":
                    parts.append(f"\nTechnical summary: {op.reasoning}")
                    if op.key_levels:
                        parts.append(f"Key levels: {json.dumps(op.key_levels)}")
                    if op.raw_data:
                        parts.append(
                            f"Technical data: {json.dumps(op.raw_data, ensure_ascii=False, default=str)[:2000]}"
                        )
        return "\n".join(parts)

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        parsed = try_parse_json(raw_text)
        if parsed is None:
            logger.warning("[SkillAgent:%s] failed to parse opinion JSON", self.skill_id)
            return None

        confidence = parsed.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            logger.warning("[SkillAgent:%s] rejected invalid confidence", self.skill_id)
            return None
        try:
            confidence_value = float(confidence)
        except (OverflowError, TypeError, ValueError):
            logger.warning("[SkillAgent:%s] rejected invalid confidence", self.skill_id)
            return None
        if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0:
            logger.warning("[SkillAgent:%s] rejected invalid confidence", self.skill_id)
            return None

        return AgentOpinion(
            agent_name=self.agent_name,
            signal=parsed.get("signal"),  # None if missing — no silent default
            confidence=confidence_value,
            reasoning=parsed.get("reasoning", ""),
            raw_data=parsed,
        )


StrategyAgent = SkillAgent
