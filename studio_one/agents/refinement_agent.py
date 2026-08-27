"""Google ADK agents for the first STUDIO//ONE workflow stages."""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel
from pydantic import Field

from studio_one.integrations.clickhouse_mcp import (
    GOOGLE_CLOUD_PROJECT,
    retrieve_project_memory_bundle,
)
from studio_one.workflow.stages import StudioOneStage


GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

RECOMMENDATION_GOVERNANCE_BOUNDARY = (
    "AI output is a non-authoritative recommendation for creator review; it is "
    "not canon, not an approval, not a human decision, and not authorization to "
    "create assets, publish, or mutate production state."
)
STORYBOARD_GOVERNANCE_STATUS = (
    "Storyboard candidate for creator approval; not approved canon or "
    "production truth."
)
NON_FABRICATION_STATEMENT = (
    "No project facts, characters, history, prior canon, assets, locations, "
    "QC records, decisions, or constraints are invented; unstated information "
    "remains unknown/open."
)

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class BrainstormResponse(BaseModel):
    stage: str
    project_id: str
    creator_intent_summary: str
    retrieved_project_facts: list[str] = Field(min_length=1, max_length=8)
    retrieved_production_constraints: list[str] = Field(min_length=1, max_length=8)
    concept_directions: list[str] = Field(min_length=2, max_length=6)
    creative_production_implications: list[str] = Field(min_length=2, max_length=6)
    intentionally_open_territory: list[str] = Field(min_length=2, max_length=6)
    creator_choices_questions: list[str] = Field(min_length=2, max_length=6)
    governance_boundary: str
    non_fabrication_statement: str


class RefineResponse(BaseModel):
    stage: str
    project_id: str
    creator_selected_or_steered_direction: str
    refined_premise: str
    hook: str
    narrative_objective: str
    emotional_objective: str
    beginning: str
    progression: str
    payoff: str
    production_implications: list[str] = Field(min_length=2, max_length=6)
    continuity_constraint_risks: list[str] = Field(min_length=1, max_length=6)
    unresolved_creative_decisions: list[str] = Field(min_length=1, max_length=6)
    storyboard_readiness_recommendation: str
    governance_boundary: str
    non_fabrication_statement: str


class StoryboardPanel(BaseModel):
    panel_shot_number: int = Field(ge=1)
    duration: str
    story_purpose: str
    visual_description: str
    visual_treatment: str
    composition: str
    camera_framing: str
    lighting: str
    environment: str
    image_generation_prompt: str
    video_generation_prompt: str
    dialogue: str
    voice_tts_direction: str
    sound_effects: list[str]
    ambience: str
    music_direction: str
    editing_notes: str
    continuity_notes: str
    asset_requirements: list[str]
    reuse_opportunities: list[str]
    production_notes: str


class StoryboardCandidate(BaseModel):
    stage: str
    project_id: str
    working_title: str
    target_total_runtime: str
    creative_narrative_objective: str
    production_constraints_applied: list[str]
    unresolved_issues: list[str]
    approval_governance_status: str
    panels: list[StoryboardPanel] = Field(min_length=1)
    non_fabrication_statement: str


def _configure_vertex_environment() -> None:
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", GOOGLE_CLOUD_PROJECT)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", GOOGLE_CLOUD_LOCATION)


def _project_context_lines(project_id: str, stage: StudioOneStage) -> list[str]:
    return [
        f"- Project id: {project_id}",
        f"- Requested stage: {stage.value}",
    ]


def _stage_task_instruction(stage: StudioOneStage) -> str:
    if stage == StudioOneStage.BRAINSTORM:
        return f"""
Stage behavior:
- Start from project.initial_creative_intent retrieved through MCP.
- Summarize creator intent without treating it as canon.
- Identify retrieved project facts and production constraints separately.
- Propose multiple concept directions and implications.
- Keep open territory explicit.
- Set stage exactly to: {StudioOneStage.BRAINSTORM.value}
- Set governance_boundary exactly to: {RECOMMENDATION_GOVERNANCE_BOUNDARY}
- Set non_fabrication_statement exactly to: {NON_FABRICATION_STATEMENT}
""".strip()

    if stage == StudioOneStage.REFINE:
        return f"""
Stage behavior:
- Use the explicit creator direction from the current message.
- Retrieve project memory again through MCP before answering.
- Refine the concept without autonomously advancing workflow authority.
- Gemini may recommend storyboard readiness, but must not claim approval or stage advancement.
- Set stage exactly to: {StudioOneStage.REFINE.value}
- Set governance_boundary exactly to: {RECOMMENDATION_GOVERNANCE_BOUNDARY}
- Set non_fabrication_statement exactly to: {NON_FABRICATION_STATEMENT}
""".strip()

    if stage == StudioOneStage.FINALIZE_STORYBOARD:
        return f"""
Stage behavior:
- Use the explicit creator action from the current message.
- Retrieve project memory again through MCP before answering.
- Produce a structured storyboard candidate with multiple ordered panels when useful.
- Include all storyboard-level and panel-level fields required by the output schema.
- Do not claim approval, canon, asset generation, publishing, or production-state mutation.
- Set stage exactly to: {StudioOneStage.FINALIZE_STORYBOARD.value}
- Set approval_governance_status exactly to: {STORYBOARD_GOVERNANCE_STATUS}
- Set non_fabrication_statement exactly to: {NON_FABRICATION_STATEMENT}
""".strip()

    raise ValueError(f"Stage is not implemented: {stage.value}")


def build_stage_agent(
    project_id: str,
    stage: StudioOneStage,
    output_schema: type[OutputModel],
) -> LlmAgent:
    if not project_id:
        raise ValueError("project_id is required")

    _configure_vertex_environment()

    async def retrieve_stage_memory() -> dict[str, Any]:
        """Retrieve project memory through official mcp-clickhouse."""
        return await retrieve_project_memory_bundle(project_id=project_id)

    project_context = "\n".join(_project_context_lines(project_id, stage))
    instruction = f"""
You are STUDIO//ONE, a human-governed production-intelligence agent for independent creators.

You must call retrieve_stage_memory before producing the final answer.
Use only the production memory returned by that tool plus explicit creator input in the current message.

Project context:
{project_context}

Global rules:
- Agent production-memory retrieval must happen through official mcp-clickhouse.
- Treat project.initial_creative_intent as durable creator-supplied context, not approved canon.
- Treat project.production_constraints as separate from initial creative intent.
- Current creator direction may supplement durable project context, but it does not replace MCP-retrieved project memory.
- AI recommendations are not approved production state and must be phrased as proposals.
- Do not invent characters, history, prior canon, assets, locations, QC records, decisions, or constraints.
- Do not create assets, perform QC, prepare post-production, publish, or mutate production state.
- The current project asset count must remain explicit where relevant.

{_stage_task_instruction(stage)}

When the task is complete, call finish_task with the structured fields required
by the provided output schema. Keep values concise and do not include markdown.
""".strip()

    return LlmAgent(
        name=f"studio_one_{stage.value}_agent",
        description=(
            "Runs a STUDIO//ONE workflow stage using MCP-retrieved "
            "ClickHouse production memory."
        ),
        model=Gemini(
            model=GEMINI_MODEL,
            client_kwargs={
                "vertexai": True,
                "project": GOOGLE_CLOUD_PROJECT,
                "location": GOOGLE_CLOUD_LOCATION,
            },
        ),
        instruction=instruction,
        tools=[FunctionTool(retrieve_stage_memory)],
        output_schema=output_schema,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
        ),
        mode="task",
    )


def _part_payload(part: types.Part) -> dict[str, Any]:
    return part.model_dump(exclude_none=True)


def _extract_tool_response(event: Any, tool_name: str) -> dict[str, Any] | None:
    if not event.content:
        return None
    for part in event.content.parts or []:
        payload = _part_payload(part)
        function_response = payload.get("function_response")
        if function_response and function_response.get("name") == tool_name:
            response = function_response.get("response")
            if isinstance(response, dict):
                return response
    return None


def _extract_function_calls(event: Any) -> list[str]:
    if not event.content:
        return []
    calls: list[str] = []
    for part in event.content.parts or []:
        payload = _part_payload(part)
        function_call = payload.get("function_call")
        if function_call and function_call.get("name"):
            calls.append(function_call["name"])
    return calls


def _extract_text_parts(event: Any) -> list[str]:
    if not event.content:
        return []
    texts: list[str] = []
    for part in event.content.parts or []:
        payload = _part_payload(part)
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)
    return texts


def _parse_structured_response(
    text_parts: list[str],
    output_schema: type[OutputModel],
) -> dict[str, Any]:
    raw = "\n".join(text_parts).strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]

    return output_schema.model_validate_json(raw).model_dump()


async def _run_stage_agent(
    project_id: str,
    stage: StudioOneStage,
    output_schema: type[OutputModel],
    user_message_text: str,
) -> dict[str, Any]:
    if not project_id:
        raise ValueError("project_id is required")

    agent = build_stage_agent(project_id, stage, output_schema)
    session_service = InMemorySessionService()
    app_name = "studio_one"
    user_id = "local_creator"
    session_id = f"{stage.value}_{uuid4()}"
    await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

    runner = Runner(
        app_name=app_name,
        agent=agent,
        session_service=session_service,
    )
    user_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message_text)],
    )

    tool_calls: list[str] = []
    tool_responses: list[str] = []
    mcp_evidence: dict[str, Any] | None = None
    production_memory: dict[str, Any] | None = None
    final_text_parts: list[str] = []
    raw_task_output: Any = None
    output: dict[str, Any] | None = None

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_message,
    ):
        tool_calls.extend(_extract_function_calls(event))
        tool_response = _extract_tool_response(event, "retrieve_stage_memory")
        if tool_response is not None:
            tool_responses.append("retrieve_stage_memory")
            mcp_evidence = tool_response.get("retrieval")
            production_memory = tool_response.get("production_memory")
        final_text_parts.extend(_extract_text_parts(event))
        event_output = getattr(event, "output", None)
        if event_output is not None:
            raw_task_output = event_output

    if raw_task_output is not None:
        if isinstance(raw_task_output, dict) and "result" in raw_task_output:
            final_text_parts = [str(raw_task_output["result"])]
        elif isinstance(raw_task_output, dict):
            output = output_schema.model_validate(raw_task_output).model_dump()
            final_text_parts = []
        else:
            final_text_parts = [str(raw_task_output)]

    if not final_text_parts and output is None:
        raise RuntimeError("ADK agent did not return a final text response")

    if output is None:
        output = _parse_structured_response(final_text_parts, output_schema)

    validation = {
        "project_memory_retrieved": bool(
            production_memory
            and production_memory.get("project", {}).get("project_id") == project_id
        ),
        "agent_memory_retrieval_path": "official_mcp_clickhouse",
        "gemini_can_advance_stage": False,
        "clickhouse_writes_performed": False,
    }

    return {
        "stage": stage.value,
        "runtime": {
            "adk_mechanism": "google.adk LlmAgent + Runner + FunctionTool",
            "agent_name": agent.name,
            "gemini_model_used": GEMINI_MODEL,
            "google_cloud_location": GOOGLE_CLOUD_LOCATION,
            "adk_tool_calls": tool_calls,
            "adk_tool_responses": tool_responses,
            "mcp_retrieval_evidence": mcp_evidence,
            "clickhouse_writes_performed": False,
        },
        "validation": validation,
        "production_memory": production_memory,
        "structured_output": output,
    }


async def run_brainstorm_agent(project_id: str) -> dict[str, Any]:
    """Run BRAINSTORM from MCP-retrieved initial creative intent."""
    return await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.BRAINSTORM,
        output_schema=BrainstormResponse,
        user_message_text=(
            "Begin BRAINSTORM from the MCP-retrieved initial creative intent "
            "and project memory."
        ),
    )


async def run_refine_agent(
    project_id: str,
    creator_direction: str,
) -> dict[str, Any]:
    """Run REFINE using explicit creator direction and MCP memory."""
    direction = creator_direction.strip()
    if not direction:
        raise ValueError("creator_direction is required for REFINE")

    return await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.REFINE,
        output_schema=RefineResponse,
        user_message_text=f"Explicit creator direction for REFINE: {direction}",
    )


async def run_finalize_storyboard_agent(
    project_id: str,
    creator_action: str,
    target_total_runtime: str | None = None,
) -> dict[str, Any]:
    """Run FINALIZE STORYBOARD using explicit creator action and MCP memory."""
    action = creator_action.strip()
    if not action:
        raise ValueError("creator_action is required for FINALIZE STORYBOARD")

    runtime_note = target_total_runtime.strip() if target_total_runtime else "unspecified"
    return await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.FINALIZE_STORYBOARD,
        output_schema=StoryboardCandidate,
        user_message_text=(
            "Explicit creator action for FINALIZE STORYBOARD: "
            f"{action}\nTarget total runtime: {runtime_note}"
        ),
    )


async def run_refinement_agent(
    project_id: str,
    creator_direction: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper for the REFINE stage."""
    if creator_direction and creator_direction.strip():
        report = await run_refine_agent(project_id, creator_direction)
    else:
        report = await run_brainstorm_agent(project_id)

    sanitized = dict(report)
    sanitized["structured_refinement"] = sanitized.get("structured_output")
    return sanitized


def sanitize_runtime_report(report: dict[str, Any]) -> dict[str, Any]:
    """Reduce large production-memory text fields for terminal proof output."""
    sanitized = json.loads(json.dumps(report))
    memory = sanitized.get("production_memory") or {}
    project = memory.get("project") or {}
    constraints = project.pop("production_constraints", "") or ""
    if constraints:
        project["production_constraints_present"] = True
        project["production_constraints_length"] = len(constraints)
        project["production_constraints_safe_excerpt"] = constraints[:240]

    initial_intent = project.pop("initial_creative_intent", "") or ""
    if initial_intent:
        project["initial_creative_intent_present"] = True
        project["initial_creative_intent_length"] = len(initial_intent)
        project["initial_creative_intent_safe_excerpt"] = initial_intent[:240]

    review = memory.get("review_queue") or {}
    for field in ("finding", "rationale", "proposed_state_change"):
        value = review.pop(field, "") or ""
        if value:
            review[f"{field}_length"] = len(value)
            if field == "proposed_state_change":
                review[f"{field}_safe_excerpt"] = value[:240]

    decision = memory.get("decision_log") or {}
    for field in ("previous_state", "resulting_state", "agent_recommendation"):
        value = decision.pop(field, "") or ""
        if value:
            decision[f"{field}_length"] = len(value)
            if field == "resulting_state":
                decision[f"{field}_safe_excerpt"] = value[:240]

    return sanitized
