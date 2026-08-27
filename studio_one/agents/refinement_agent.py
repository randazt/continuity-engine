"""Google ADK agents for the first STUDIO//ONE workflow stages."""

from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable, Literal, TypeVar
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from studio_one.integrations.clickhouse_mcp import (
    GOOGLE_CLOUD_PROJECT,
    retrieve_project_memory_bundle,
    retrieve_qc_memory_bundle,
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
GENERATE_ASSETS_GOVERNANCE_BOUNDARY = (
    "GENERATE ASSETS produces provider-neutral instructions for creator-operated "
    "asset generation and reuse decisions; no image, video, or dialogue audio "
    "has been generated, no asset has been created, and no asset is QC-approved."
)
ASSET_STATE_BOUNDARY = (
    "asset_requirement != generation_prompt != externally_generated_asset != "
    "qc_approved_asset"
)
PROVIDER_SELECTION_BOUNDARY = (
    "The creator selects and operates any external generation tools; STUDIO//ONE "
    "does not choose or call an image, video, or TTS provider."
)
QUALITY_CONTROL_GOVERNANCE_BOUNDARY = (
    "QUALITY CONTROL output is an AI recommendation only; creator decision and "
    "controlled application persistence are required before any asset-library "
    "change."
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


class AssetRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    storyboard_reference: str
    narrative_purpose: str
    asset_requirement_type: str
    description: str
    classification: Literal["reusable_existing_asset", "missing_asset"]
    reuse_assessment: str
    source_provenance_references: list[str]


class ReusableExistingAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    storyboard_reference: str
    asset_id: str
    asset_type: str
    name: str
    reuse_rationale: str
    continuity_notes: str
    source_provenance_references: list[str]


class MissingAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    storyboard_reference: str
    asset_requirement_type: str
    description: str
    reason_no_reusable_asset_found: str
    source_provenance_references: list[str]


class ImagePromptPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int = Field(ge=1)
    storyboard_reference: str
    narrative_purpose: str
    asset_requirement_type: str
    reuse_assessment: str
    production_constraints: list[str]
    composition: str
    camera_framing: str
    environment: str
    lighting: str
    subject_character_requirements: str
    continuity_requirements: list[str]
    technical_requirements: list[str]
    positive_image_prompt: str
    negative_avoid_instructions: str
    source_provenance_references: list[str]


class VideoPromptPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard_reference: str
    approved_still_image_dependency: str
    starting_frame_intent: str
    ending_frame_intent: str
    motion_description: str
    camera_motion: str
    environmental_motion: str
    character_subject_motion: str
    duration: str
    continuity_requirements: list[str]
    video_generation_prompt: str
    source_provenance_references: list[str]


class DialogueAudioHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard_reference: str
    speaker_role: str
    exact_dialogue: str
    emotion: str
    pacing: str
    delivery: str
    pauses: str
    breathing: str
    emphasis: str
    continuity_voice_notes: str


class SoundMusicHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard_reference: str
    sound_effects: list[str]
    ambience: str
    music_direction: str
    source_provenance_references: list[str]


class GenerateAssetsPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    project_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int = Field(ge=1)
    package_status: Literal["instructions_for_creator"]
    asset_requirements: list[AssetRequirement]
    reusable_existing_assets: list[ReusableExistingAsset]
    missing_assets: list[MissingAsset]
    image_prompt_packages: list[ImagePromptPackage]
    video_prompt_packages: list[VideoPromptPackage]
    dialogue_audio_handoffs: list[DialogueAudioHandoff]
    sound_music_handoffs: list[SoundMusicHandoff]
    provenance_references: list[str]
    governance_boundary: str
    asset_state_boundary: str
    provider_selection_boundary: str


class QualityControlAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    project_id: str
    external_asset_candidate_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int = Field(ge=1)
    source_generation_package_id: str | None = None
    source_generation_package_version: int = Field(ge=0)
    evaluated_asset_type: str
    storyboard_alignment: str
    prompt_instruction_alignment: str
    continuity_assessment: str
    production_constraint_assessment: str
    technical_quality_assessment: str
    dialogue_audio_assessment: str
    provenance_assessment: str
    detected_issues: list[str]
    required_corrections: list[str]
    strengths: list[str]
    recommendation: Literal[
        "recommend_approve",
        "recommend_reject",
        "recommend_revision",
    ]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    evidence_references: list[str]
    governance_boundary: str
    non_fabrication_statement: str


class ApprovedStoryboardRequiredError(RuntimeError):
    """Raised when GENERATE ASSETS is requested without approved storyboard state."""


class QualityControlContextRequiredError(RuntimeError):
    """Raised when QUALITY CONTROL lacks exact candidate provenance context."""


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

    if stage == StudioOneStage.GENERATE_ASSETS:
        return f"""
Stage behavior:
- This stage means asset planning, reuse audit, and prompt/handoff package creation.
- Use only the latest approved storyboard returned in production_memory.latest_approved_storyboard.
- A pending storyboard candidate in review_queue is insufficient.
- Use production_memory.assets as the existing project asset inventory.
- For every approved storyboard panel or shot, extract required production assets.
- Evaluate reuse before declaring any missing asset.
- Classify each asset requirement exactly as reusable_existing_asset or missing_asset.
- Do not fabricate reusable assets. If production_memory.assets is empty, reusable_existing_assets must be empty and missing asset reasons must say no reusable assets were found.
- Create ImagePromptPackage records only for missing visual assets.
- Create VideoPromptPackage records only where the approved storyboard indicates motion or video instructions.
- Create DialogueAudioHandoff records only where spoken dialogue exists.
- Preserve SFX, ambience, and music direction in SoundMusicHandoff records.
- Prompts and handoff instructions are not assets.
- Do not claim that images, video, speech, external assets, or QC-approved assets were created.
- Do not name or choose an external generation provider.
- Do not advance to QUALITY CONTROL.
- Set stage exactly to: {StudioOneStage.GENERATE_ASSETS.value}
- Set package_status exactly to: instructions_for_creator
- Set governance_boundary exactly to: {GENERATE_ASSETS_GOVERNANCE_BOUNDARY}
- Set asset_state_boundary exactly to: {ASSET_STATE_BOUNDARY}
- Set provider_selection_boundary exactly to: {PROVIDER_SELECTION_BOUNDARY}
""".strip()

    if stage == StudioOneStage.QUALITY_CONTROL:
        return f"""
Stage behavior:
- Evaluate only the MCP-retrieved external asset candidate against the exact approved storyboard, relevant panel/shot, exact generation package when present, project constraints, and existing approved asset context.
- A generation package by itself is insufficient; an approved storyboard by itself is insufficient.
- Do not claim approval, promotion, or authoritative asset-library state.
- Do not output fields named approved, approved_for_promotion, qc_approved_asset, human_approved, or promoted_to_assets.
- Set recommendation exactly to one of: recommend_approve, recommend_reject, recommend_revision.
- Treat the recommendation as an AI recommendation only.
- Set stage exactly to: {StudioOneStage.QUALITY_CONTROL.value}
- Set governance_boundary exactly to: {QUALITY_CONTROL_GOVERNANCE_BOUNDARY}
- Set non_fabrication_statement exactly to: {NON_FABRICATION_STATEMENT}
""".strip()

    raise ValueError(f"Stage is not implemented: {stage.value}")


def build_stage_agent(
    project_id: str,
    stage: StudioOneStage,
    output_schema: type[OutputModel],
    memory_retriever: Callable[[], Awaitable[dict[str, Any]]] | None = None,
) -> LlmAgent:
    if not project_id:
        raise ValueError("project_id is required")

    _configure_vertex_environment()

    async def retrieve_stage_memory() -> dict[str, Any]:
        """Retrieve project memory through official mcp-clickhouse."""
        if memory_retriever is not None:
            return await memory_retriever()
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
- Do not create assets, prepare post-production, publish, or mutate production state from inside the agent.
- Perform QUALITY CONTROL only when the requested stage is quality_control.
- Do not call or choose external image, video, or TTS providers.
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
    memory_retriever: Callable[[], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not project_id:
        raise ValueError("project_id is required")

    agent = build_stage_agent(
        project_id,
        stage,
        output_schema,
        memory_retriever=memory_retriever,
    )
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


def _require_generate_assets_memory(production_memory: dict[str, Any] | None) -> None:
    if not production_memory:
        raise ApprovedStoryboardRequiredError(
            "GENERATE ASSETS requires MCP-retrieved production memory"
        )

    storyboard = production_memory.get("latest_approved_storyboard")
    if not storyboard:
        raise ApprovedStoryboardRequiredError(
            "GENERATE ASSETS requires an approved storyboard; pending candidates "
            "in review_queue are insufficient"
        )

    if storyboard.get("status") != "approved":
        raise ApprovedStoryboardRequiredError("latest storyboard is not approved")
    if storyboard.get("approval_status") != "approved":
        raise ApprovedStoryboardRequiredError(
            "latest storyboard approval_status is not approved"
        )
    if storyboard.get("authority_level") != "approved_production_state":
        raise ApprovedStoryboardRequiredError(
            "latest storyboard is not authoritative production state"
        )


def _validate_generate_assets_package(report: dict[str, Any]) -> None:
    output = GenerateAssetsPackage.model_validate(report["structured_output"])
    if output.stage != StudioOneStage.GENERATE_ASSETS.value:
        raise RuntimeError("GENERATE ASSETS output used the wrong stage")
    if output.governance_boundary != GENERATE_ASSETS_GOVERNANCE_BOUNDARY:
        raise RuntimeError("GENERATE ASSETS governance boundary changed")
    if output.asset_state_boundary != ASSET_STATE_BOUNDARY:
        raise RuntimeError("GENERATE ASSETS asset-state boundary changed")
    if output.provider_selection_boundary != PROVIDER_SELECTION_BOUNDARY:
        raise RuntimeError("GENERATE ASSETS provider-selection boundary changed")

    memory = report.get("production_memory") or {}
    storyboard = memory.get("latest_approved_storyboard") or {}
    if output.approved_storyboard_id != storyboard.get("storyboard_id"):
        raise RuntimeError("package does not reference the MCP-approved storyboard")
    if output.approved_storyboard_version != int(storyboard.get("storyboard_version")):
        raise RuntimeError("package does not reference the approved storyboard version")

    existing_assets = memory.get("assets") or []
    if not existing_assets and output.reusable_existing_assets:
        raise RuntimeError("reusable assets were fabricated from empty asset inventory")


def _require_quality_control_memory(
    production_memory: dict[str, Any] | None,
    expected_project_id: str,
    expected_candidate_id: str,
) -> None:
    if not production_memory:
        raise QualityControlContextRequiredError(
            "QUALITY CONTROL requires MCP-retrieved production memory"
        )

    project = production_memory.get("project") or {}
    if project.get("project_id") != expected_project_id:
        raise QualityControlContextRequiredError(
            "retrieved project does not match requested project"
        )

    candidate = production_memory.get("external_asset_candidate")
    if not candidate:
        raise QualityControlContextRequiredError(
            "QUALITY CONTROL requires an external asset intake candidate"
        )
    if candidate.get("project_id") != expected_project_id:
        raise QualityControlContextRequiredError(
            "external asset candidate does not belong to requested project"
        )
    if candidate.get("external_asset_candidate_id") != expected_candidate_id:
        raise QualityControlContextRequiredError(
            "external asset candidate does not match requested candidate"
        )
    if candidate.get("intake_status") != "submitted_for_qc":
        raise QualityControlContextRequiredError(
            "external asset candidate is not submitted for QC"
        )
    if candidate.get("qc_status") != "pending_qc":
        raise QualityControlContextRequiredError(
            "external asset candidate is not pending QC"
        )
    if candidate.get("authority_level") != "external_asset_candidate":
        raise QualityControlContextRequiredError(
            "external asset candidate authority level is invalid"
        )
    if not candidate.get("external_asset_reference"):
        raise QualityControlContextRequiredError(
            "external asset candidate must include creator-submitted media reference"
        )

    storyboard = production_memory.get("approved_storyboard")
    if not storyboard:
        raise QualityControlContextRequiredError(
            "QUALITY CONTROL requires the exact approved storyboard version"
        )
    if storyboard.get("status") != "approved":
        raise QualityControlContextRequiredError("storyboard is not approved")
    if storyboard.get("approval_status") != "approved":
        raise QualityControlContextRequiredError(
            "storyboard approval_status is not approved"
        )
    if storyboard.get("authority_level") != "approved_production_state":
        raise QualityControlContextRequiredError(
            "storyboard is not authoritative production state"
        )
    if storyboard.get("storyboard_id") != candidate.get("approved_storyboard_id"):
        raise QualityControlContextRequiredError(
            "candidate storyboard_id does not match retrieved storyboard"
        )
    if int(storyboard.get("storyboard_version") or 0) != int(
        candidate.get("approved_storyboard_version") or 0
    ):
        raise QualityControlContextRequiredError(
            "candidate storyboard_version does not match retrieved storyboard"
        )
    if not production_memory.get("relevant_storyboard_panel"):
        raise QualityControlContextRequiredError(
            "QUALITY CONTROL requires the relevant storyboard panel/shot"
        )

    package_id = _optional_memory_id(candidate.get("source_generation_package_id"))
    package_version = int(candidate.get("source_generation_package_version") or 0)
    package = production_memory.get("generation_package")
    if package_id:
        if not package:
            raise QualityControlContextRequiredError(
                "candidate references a generation package that was not retrieved"
            )
        if package.get("generation_package_id") != package_id:
            raise QualityControlContextRequiredError(
                "retrieved generation package ID does not match candidate"
            )
        if int(package.get("package_version") or 0) != package_version:
            raise QualityControlContextRequiredError(
                "retrieved generation package version does not match candidate"
            )
        if package.get("approved_storyboard_id") != candidate.get(
            "approved_storyboard_id"
        ):
            raise QualityControlContextRequiredError(
                "generation package storyboard_id does not match candidate"
            )
        if int(package.get("approved_storyboard_version") or 0) != int(
            candidate.get("approved_storyboard_version") or 0
        ):
            raise QualityControlContextRequiredError(
                "generation package storyboard_version does not match candidate"
            )
        if package.get("storyboard_panel_shot_reference") != candidate.get(
            "storyboard_panel_shot_reference"
        ):
            raise QualityControlContextRequiredError(
                "generation package storyboard reference does not match candidate"
            )
        if package.get("status") != "instructions_for_creator":
            raise QualityControlContextRequiredError(
                "generation package is not an instruction package"
            )
        if package.get("authority_level") != "production_instruction":
            raise QualityControlContextRequiredError(
                "generation package authority level is invalid"
            )
    elif package_version:
        raise QualityControlContextRequiredError(
            "generation package version requires generation package ID"
        )


def _validate_quality_control_assessment(report: dict[str, Any]) -> None:
    output = QualityControlAssessment.model_validate(report["structured_output"])
    if output.stage != StudioOneStage.QUALITY_CONTROL.value:
        raise RuntimeError("QUALITY CONTROL output used the wrong stage")
    if output.governance_boundary != QUALITY_CONTROL_GOVERNANCE_BOUNDARY:
        raise RuntimeError("QUALITY CONTROL governance boundary changed")
    if output.non_fabrication_statement != NON_FABRICATION_STATEMENT:
        raise RuntimeError("QUALITY CONTROL non-fabrication statement changed")

    memory = report.get("production_memory") or {}
    candidate = memory.get("external_asset_candidate") or {}
    storyboard = memory.get("approved_storyboard") or {}
    package = memory.get("generation_package") or {}
    if output.project_id != candidate.get("project_id"):
        raise RuntimeError("QC assessment project_id does not match candidate")
    if output.external_asset_candidate_id != candidate.get(
        "external_asset_candidate_id"
    ):
        raise RuntimeError("QC assessment candidate_id does not match MCP candidate")
    if output.approved_storyboard_id != storyboard.get("storyboard_id"):
        raise RuntimeError("QC assessment storyboard_id does not match MCP storyboard")
    if output.approved_storyboard_version != int(
        storyboard.get("storyboard_version") or 0
    ):
        raise RuntimeError(
            "QC assessment storyboard_version does not match MCP storyboard"
        )
    if output.evaluated_asset_type != candidate.get("asset_type"):
        raise RuntimeError("QC assessment asset type does not match MCP candidate")

    package_id = _optional_memory_id(candidate.get("source_generation_package_id"))
    if package_id:
        if output.source_generation_package_id != package_id:
            raise RuntimeError(
                "QC assessment package_id does not match MCP candidate"
            )
        if output.source_generation_package_version != int(
            candidate.get("source_generation_package_version") or 0
        ):
            raise RuntimeError(
                "QC assessment package_version does not match MCP candidate"
            )
        if package.get("generation_package_id") != package_id:
            raise RuntimeError("MCP generation package does not match candidate")
    else:
        if output.source_generation_package_id is not None:
            raise RuntimeError("QC assessment invented a generation package ID")
        if output.source_generation_package_version != 0:
            raise RuntimeError("QC assessment invented a generation package version")

    prohibited_values = {
        "approved",
        "approved_for_promotion",
        "qc_approved_asset",
        "human_approved",
        "promoted_to_assets",
    }
    for value in _string_values(output.model_dump()):
        if value in prohibited_values:
            raise RuntimeError("QC assessment contained an approval-state value")


def _optional_memory_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_string_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_string_values(item))
        return values
    return []


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


async def run_generate_assets_agent(project_id: str) -> dict[str, Any]:
    """Run GENERATE ASSETS only when MCP returns an approved storyboard."""
    preflight = await retrieve_project_memory_bundle(project_id=project_id)
    _require_generate_assets_memory(preflight.get("production_memory"))

    report = await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.GENERATE_ASSETS,
        output_schema=GenerateAssetsPackage,
        user_message_text=(
            "Prepare the GENERATE ASSETS package from the MCP-retrieved "
            "approved storyboard and existing asset inventory. Do not generate "
            "images, video, or dialogue audio."
        ),
    )
    _require_generate_assets_memory(report.get("production_memory"))
    _validate_generate_assets_package(report)
    report["validation"].update(
        {
            "approved_storyboard_required": True,
            "approved_storyboard_found": True,
            "existing_assets_checked_before_missing_assets": True,
            "asset_rows_created": 0,
            "external_generation_provider_called": False,
            "gemini_can_mark_assets_generated_or_qc_approved": False,
        }
    )
    return report


async def run_quality_control_agent(
    project_id: str,
    external_asset_candidate_id: str,
) -> dict[str, Any]:
    """Run QUALITY CONTROL against one MCP-retrieved external asset candidate."""
    candidate_id = external_asset_candidate_id.strip()
    if not candidate_id:
        raise ValueError("external_asset_candidate_id is required")

    async def retrieve_qc_stage_memory() -> dict[str, Any]:
        return await retrieve_qc_memory_bundle(
            project_id=project_id,
            external_asset_candidate_id=candidate_id,
        )

    preflight = await retrieve_qc_stage_memory()
    _require_quality_control_memory(
        preflight.get("production_memory"),
        project_id,
        candidate_id,
    )

    report = await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.QUALITY_CONTROL,
        output_schema=QualityControlAssessment,
        user_message_text=(
            "Evaluate the MCP-retrieved external asset candidate against the "
            "exact approved storyboard, relevant panel/shot, package "
            "instructions when present, project constraints, and existing "
            "approved asset context. Return only an AI QC recommendation."
        ),
        memory_retriever=retrieve_qc_stage_memory,
    )
    _require_quality_control_memory(
        report.get("production_memory"),
        project_id,
        candidate_id,
    )
    _validate_quality_control_assessment(report)
    report["validation"].update(
        {
            "external_asset_candidate_required": True,
            "candidate_found": True,
            "exact_approved_storyboard_required": True,
            "exact_generation_package_checked_when_present": True,
            "agent_memory_retrieval_path": "official_mcp_clickhouse",
            "review_queue_rows_created_by_agent": 0,
            "asset_rows_created_by_agent": 0,
            "gemini_can_approve_or_promote_asset": False,
        }
    )
    return report


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
