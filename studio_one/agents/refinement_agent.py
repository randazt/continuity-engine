"""Google ADK agents for the first STUDIO//ONE workflow stages."""

from __future__ import annotations

import json
import os
import re
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
    retrieve_post_production_memory_bundle,
    retrieve_project_memory_bundle,
    retrieve_publish_memory_bundle,
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
POST_PRODUCTION_GOVERNANCE_BOUNDARY = (
    "POST PRODUCTION output is provider-neutral editing instructions for the "
    "creator's external edit; STUDIO//ONE has not edited, rendered, uploaded, "
    "published, or marked the production complete."
)
PUBLISH_GOVERNANCE_BOUNDARY = (
    "PUBLISH output is a provider-neutral publishing-prep package for creator "
    "approval and manual posting; STUDIO//ONE has not authenticated to social "
    "media, video platforms, websites, or external services, called publishing "
    "APIs, uploaded media, scheduled content, posted content, or made content "
    "live."
)
GENERIC_PLATFORM_VARIANTS = (
    "short-form social",
    "long-form video",
    "general social post",
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


class ApprovedAssetCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storyboard_reference: str
    required_asset: str
    coverage_status: Literal["covered", "missing", "unresolved_qc"]
    approved_asset_references: list[str]
    notes: str


class PostProductionReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_storyboard_present: bool
    required_storyboard_shots_panels: list[str]
    approved_asset_coverage_per_shot: list[ApprovedAssetCoverage]
    missing_required_assets: list[str]
    unresolved_qc_issues: list[str]
    dialogue_availability: list[str]
    sound_effects_requirements: list[str]
    ambience_requirements: list[str]
    music_requirements: list[str]
    continuity_concerns: list[str]
    unresolved_production_issues: list[str]
    readiness_status: Literal[
        "ready_for_editing_package",
        "not_ready_missing_assets",
        "not_ready_unresolved_qc",
        "not_ready_other",
    ]
    return_to_stage: Literal["", "generate_assets", "quality_control"]


class OrderedEditSequenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_shot_number: int = Field(ge=1)
    approved_asset_references: list[str]
    intended_duration: str
    storyboard_purpose: str
    visual_treatment: str
    framing_composition_reference: str
    video_motion_intent: str
    dialogue: str
    voice_performance_direction: str
    sound_effects: list[str]
    ambience: str
    music_cue: str
    transition_into_shot: str
    transition_out_of_shot: str
    editorial_movement_camera_notes: str
    pacing_hold_notes: str
    continuity_notes: str
    approved_asset_provenance: list[str]


class PostProductionPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    project_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int = Field(ge=1)
    package_status: Literal["instructions_for_creator_edit"]
    readiness: PostProductionReadiness
    target_runtime: str
    creative_narrative_objective: str
    production_constraints: list[str]
    ordered_edit_sequence: list[OrderedEditSequenceItem]
    audio_plan: str
    music_plan: str
    continuity_notes: list[str]
    unresolved_notes: list[str]
    provenance_references: list[str]
    governance_boundary: str
    non_fabrication_statement: str


class PublishingReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_storyboard_present: bool
    final_edit_context_supplied: bool
    final_edit_claim_is_creator_supplied: bool
    unresolved_qc_issues: list[str]
    missing_required_metadata: list[str]
    readiness_status: Literal[
        "ready_for_publish_package",
        "not_ready_missing_final_edit_context",
        "not_ready_unresolved_qc",
        "not_ready_missing_required_metadata",
    ]
    return_to_stage: Literal["", "post_production", "quality_control"]
    notes: list[str]


class PublishTextOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    text: str
    rationale: str
    source_provenance_references: list[str]


class PublishKeywordOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    keywords: list[str]
    rationale: str
    source_provenance_references: list[str]


class PublishHashtagOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    hashtags: list[str]
    rationale: str
    source_provenance_references: list[str]


class PlatformCopyOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_variant: str
    recommended_title: str
    short_caption: str
    long_description: str
    hashtags: list[str]
    cta: str
    seo_terms: list[str]
    metadata_notes: list[str]
    source_provenance_references: list[str]


class RecommendedPublishOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title_option_id: str
    caption_option_id: str
    description_option_id: str
    hashtag_option_id: str
    rationale: str


class PublishPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    project_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int = Field(ge=1)
    final_edit_reference: str | None = None
    publishing_readiness: PublishingReadiness
    title_options: list[PublishTextOption]
    seo_keyword_options: list[PublishKeywordOption]
    caption_options: list[PublishTextOption]
    description_options: list[PublishTextOption]
    hashtag_options: list[PublishHashtagOption]
    platform_copy_options: list[PlatformCopyOption]
    thumbnail_key_art_guidance: list[str]
    accessibility_caption_notes: list[str]
    recommended_options: RecommendedPublishOptions | None = None
    provenance_references: list[str]
    governance_boundary: str
    non_fabrication_statement: str


class ApprovedStoryboardRequiredError(RuntimeError):
    """Raised when GENERATE ASSETS is requested without approved storyboard state."""


class QualityControlContextRequiredError(RuntimeError):
    """Raised when QUALITY CONTROL lacks exact candidate provenance context."""


class PostProductionContextRequiredError(RuntimeError):
    """Raised when POST PRODUCTION lacks approved production context."""


class PublishContextRequiredError(RuntimeError):
    """Raised when PUBLISH lacks approved production context."""


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

    if stage == StudioOneStage.POST_PRODUCTION:
        return f"""
Stage behavior:
- Prepare a provider-neutral editing package for creator-operated external editing.
- Use only MCP-retrieved approved production state: project context, latest approved storyboard, approved_assets, unresolved_qc_issues, and decision_log_entries.
- Fail conceptually if no latest approved storyboard exists; a pending storyboard candidate is insufficient.
- First produce the structured readiness assessment.
- Evaluate asset readiness against approved storyboard requirements, not every possible asset type universally.
- Treat only production_memory.approved_assets as production-ready media.
- Do not treat generation packages, pending external candidates, rejected candidates, or needs-revision candidates as approved assets.
- If required assets are missing, set readiness_status to not_ready_missing_assets and return_to_stage to generate_assets.
- If unresolved QC issues block editing readiness, set readiness_status to not_ready_unresolved_qc and return_to_stage to quality_control.
- If ready, create ordered_edit_sequence from the approved storyboard order using approved assets only.
- Include timing, dialogue, voice-performance direction, SFX, ambience, music cues, transitions, editorial movement guidance, pacing, continuity reminders, and approved asset mapping as structured fields.
- Do not operate an external editor, render video, manipulate timelines, upload media to editing software, publish, or claim the finished production has been edited.
- Set stage exactly to: {StudioOneStage.POST_PRODUCTION.value}
- Set package_status exactly to: instructions_for_creator_edit
- Set governance_boundary exactly to: {POST_PRODUCTION_GOVERNANCE_BOUNDARY}
- Set non_fabrication_statement exactly to: {NON_FABRICATION_STATEMENT}
""".strip()

    if stage == StudioOneStage.PUBLISH:
        return f"""
Stage behavior:
- Prepare a provider-neutral PublishPackage for creator approval and manual posting.
- Use only MCP-retrieved approved production state: project context, production constraints, latest approved storyboard, approved_assets, unresolved_qc_issues, and decision_log_entries, plus creator-supplied final-edit details in the current message.
- A pending storyboard candidate is insufficient; PUBLISH requires latest approved storyboard production state.
- Do not require or assume a durable POST PRODUCTION table. Use the request-scoped POST PRODUCTION package only when the caller supplied one in the current request.
- Do not claim final media has been edited unless the current message explicitly says final_edit_is_complete is true and supplies a nonempty final_edit_reference.
- If final edit context is missing, set readiness_status to not_ready_missing_final_edit_context and return_to_stage to post_production.
- If unresolved QC issues exist, set readiness_status to not_ready_unresolved_qc and return_to_stage to quality_control unless missing final-edit context is the blocker being reported.
- If required publishing metadata cannot be derived from MCP memory or creator-supplied final-edit details, set readiness_status to not_ready_missing_required_metadata and list the missing fields.
- If ready, set readiness_status to ready_for_publish_package and produce title, SEO keyword, caption, description, hashtag, platform copy, thumbnail/key-art guidance, and accessibility/caption-note options.
- Use generic platform variants by default: short-form social, long-form video, and general social post.
- Do not name a specific platform unless the creator explicitly requested it in the current message.
- All copy is optional recommendation material for creator approval. You may recommend strongest title, caption, description, and hashtag option IDs, but not approve them.
- Do not authenticate to social media, video platforms, websites, or external services, call publishing APIs, upload media, schedule posts, click publish, post content, claim published, claim scheduled, claim uploaded, claim live, or mutate production state.
- Set stage exactly to: {StudioOneStage.PUBLISH.value}
- Set governance_boundary exactly to: {PUBLISH_GOVERNANCE_BOUNDARY}
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
- Do not create assets, render/edit video, publish, or mutate production state from inside the agent.
- Perform QUALITY CONTROL only when the requested stage is quality_control.
- Prepare POST PRODUCTION editing instructions only when the requested stage is post_production.
- Prepare PUBLISH package options only when the requested stage is publish.
- Do not call or choose external image, video, or TTS providers.
- Do not authenticate to social platforms, call publishing APIs, upload media, schedule posts, click publish, or claim content is live.
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


def _require_post_production_memory(
    production_memory: dict[str, Any] | None,
    expected_project_id: str,
) -> None:
    if not production_memory:
        raise PostProductionContextRequiredError(
            "POST PRODUCTION requires MCP-retrieved production memory"
        )

    project = production_memory.get("project") or {}
    if project.get("project_id") != expected_project_id:
        raise PostProductionContextRequiredError(
            "retrieved project does not match requested project"
        )

    storyboard = production_memory.get("latest_approved_storyboard")
    if not storyboard:
        raise PostProductionContextRequiredError(
            "POST PRODUCTION requires a latest approved storyboard"
        )
    if storyboard.get("status") != "approved":
        raise PostProductionContextRequiredError("latest storyboard is not approved")
    if storyboard.get("approval_status") != "approved":
        raise PostProductionContextRequiredError(
            "latest storyboard approval_status is not approved"
        )
    if storyboard.get("authority_level") != "approved_production_state":
        raise PostProductionContextRequiredError(
            "latest storyboard is not authoritative production state"
        )


def _approved_asset_reference_tokens(asset: dict[str, Any]) -> list[str]:
    if (
        asset.get("approval_status") != "approved"
        or asset.get("authority_level") != "approved_production_state"
    ):
        return []

    tokens = [
        asset.get("asset_id"),
        asset.get("external_asset_reference"),
        asset.get("source_reference"),
    ]
    return [str(token) for token in tokens if str(token or "").strip()]


def _references_approved_asset(
    reference: str,
    approved_assets: list[dict[str, Any]],
) -> bool:
    reference_text = str(reference or "").strip()
    if not reference_text:
        return False
    for asset in approved_assets:
        for token in _approved_asset_reference_tokens(asset):
            if token and token in reference_text:
                return True
    return False


def _validate_post_production_package(report: dict[str, Any]) -> None:
    output = PostProductionPackage.model_validate(report["structured_output"])
    if output.stage != StudioOneStage.POST_PRODUCTION.value:
        raise RuntimeError("POST PRODUCTION output used the wrong stage")
    if output.package_status != "instructions_for_creator_edit":
        raise RuntimeError("POST PRODUCTION output used the wrong package status")
    if output.governance_boundary != POST_PRODUCTION_GOVERNANCE_BOUNDARY:
        raise RuntimeError("POST PRODUCTION governance boundary changed")
    if output.non_fabrication_statement != NON_FABRICATION_STATEMENT:
        raise RuntimeError("POST PRODUCTION non-fabrication statement changed")

    memory = report.get("production_memory") or {}
    storyboard = memory.get("latest_approved_storyboard") or {}
    if output.project_id != storyboard.get("project_id"):
        raise RuntimeError("POST PRODUCTION project_id does not match storyboard")
    if output.approved_storyboard_id != storyboard.get("storyboard_id"):
        raise RuntimeError(
            "POST PRODUCTION package does not reference the MCP-approved storyboard"
        )
    if output.approved_storyboard_version != int(
        storyboard.get("storyboard_version") or 0
    ):
        raise RuntimeError(
            "POST PRODUCTION package does not reference the approved storyboard version"
        )

    if output.readiness.approved_storyboard_present is not True:
        raise RuntimeError("POST PRODUCTION output ignored the approved storyboard")

    if (
        output.readiness.readiness_status == "ready_for_editing_package"
        and not output.ordered_edit_sequence
    ):
        raise RuntimeError("ready editing package requires ordered edit sequence")
    if (
        output.readiness.readiness_status == "ready_for_editing_package"
        and output.readiness.missing_required_assets
    ):
        raise RuntimeError("ready editing package cannot include missing assets")
    if (
        output.readiness.readiness_status == "ready_for_editing_package"
        and output.readiness.unresolved_qc_issues
    ):
        raise RuntimeError("ready editing package cannot include unresolved QC issues")

    approved_assets = memory.get("approved_assets") or []
    for item in output.ordered_edit_sequence:
        for reference in item.approved_asset_references:
            if not _references_approved_asset(reference, approved_assets):
                raise RuntimeError(
                    "ordered edit sequence referenced non-approved asset state"
                )
        for reference in item.approved_asset_provenance:
            if not _references_approved_asset(reference, approved_assets):
                raise RuntimeError(
                    "ordered edit sequence used non-approved asset provenance"
                )

    prohibited_claims = {
        "edited_complete",
        "editing complete",
        "final edit complete",
        "rendered final video",
        "uploaded to editor",
        "timeline manipulated",
    }
    for value in _string_values(output.model_dump()):
        normalized = value.strip().lower()
        if any(claim in normalized for claim in prohibited_claims):
            raise RuntimeError(
                "POST PRODUCTION package claimed editing, rendering, upload, or publish completion"
            )


def _require_publish_memory(
    production_memory: dict[str, Any] | None,
    expected_project_id: str,
) -> None:
    if not production_memory:
        raise PublishContextRequiredError(
            "PUBLISH requires MCP-retrieved production memory"
        )

    project = production_memory.get("project") or {}
    if project.get("project_id") != expected_project_id:
        raise PublishContextRequiredError(
            "retrieved project does not match requested project"
        )

    storyboard = production_memory.get("latest_approved_storyboard")
    if not storyboard:
        raise PublishContextRequiredError(
            "PUBLISH requires a latest approved storyboard"
        )
    if storyboard.get("status") != "approved":
        raise PublishContextRequiredError("latest storyboard is not approved")
    if storyboard.get("approval_status") != "approved":
        raise PublishContextRequiredError(
            "latest storyboard approval_status is not approved"
        )
    if storyboard.get("authority_level") != "approved_production_state":
        raise PublishContextRequiredError(
            "latest storyboard is not authoritative production state"
        )


def _validate_publish_package(report: dict[str, Any]) -> None:
    output = PublishPackage.model_validate(report["structured_output"])
    if output.stage != StudioOneStage.PUBLISH.value:
        raise RuntimeError("PUBLISH output used the wrong stage")
    if output.governance_boundary != PUBLISH_GOVERNANCE_BOUNDARY:
        raise RuntimeError("PUBLISH governance boundary changed")
    if output.non_fabrication_statement != NON_FABRICATION_STATEMENT:
        raise RuntimeError("PUBLISH non-fabrication statement changed")

    memory = report.get("production_memory") or {}
    storyboard = memory.get("latest_approved_storyboard") or {}
    if output.project_id != storyboard.get("project_id"):
        raise RuntimeError("PUBLISH project_id does not match storyboard")
    if output.approved_storyboard_id != storyboard.get("storyboard_id"):
        raise RuntimeError(
            "PUBLISH package does not reference the MCP-approved storyboard"
        )
    if output.approved_storyboard_version != int(
        storyboard.get("storyboard_version") or 0
    ):
        raise RuntimeError(
            "PUBLISH package does not reference the approved storyboard version"
        )
    if output.publishing_readiness.approved_storyboard_present is not True:
        raise RuntimeError("PUBLISH output ignored the approved storyboard")

    request_context = report.get("request_context") or {}
    final_edit_reference = _optional_memory_id(
        request_context.get("final_edit_reference")
    )
    final_edit_is_complete = bool(request_context.get("final_edit_is_complete"))
    final_edit_context_supplied = bool(final_edit_reference and final_edit_is_complete)
    if output.final_edit_reference:
        if output.final_edit_reference != final_edit_reference:
            raise RuntimeError(
                "PUBLISH package final_edit_reference was not creator supplied"
            )
    if final_edit_context_supplied and output.final_edit_reference != final_edit_reference:
        raise RuntimeError(
            "PUBLISH package omitted the creator-supplied final_edit_reference"
        )
    if (
        output.publishing_readiness.final_edit_context_supplied
        != final_edit_context_supplied
    ):
        raise RuntimeError(
            "PUBLISH readiness final-edit context flag does not match creator input"
        )
    if (
        output.publishing_readiness.final_edit_claim_is_creator_supplied
        != final_edit_context_supplied
    ):
        raise RuntimeError(
            "PUBLISH readiness claimed edited media without creator confirmation"
        )

    readiness_status = output.publishing_readiness.readiness_status
    unresolved_qc = memory.get("unresolved_qc_issues") or []
    if not final_edit_context_supplied and (
        readiness_status != "not_ready_missing_final_edit_context"
    ):
        raise RuntimeError(
            "PUBLISH must report missing final-edit context before ready state"
        )
    if (
        final_edit_context_supplied
        and unresolved_qc
        and readiness_status == "ready_for_publish_package"
    ):
        raise RuntimeError("unresolved QC prevents publish-ready state")
    if readiness_status == "not_ready_unresolved_qc" and not (
        unresolved_qc or output.publishing_readiness.unresolved_qc_issues
    ):
        raise RuntimeError("PUBLISH reported unresolved QC without QC evidence")
    if (
        readiness_status == "not_ready_missing_required_metadata"
        and not output.publishing_readiness.missing_required_metadata
    ):
        raise RuntimeError(
            "PUBLISH missing metadata status requires missing metadata details"
        )
    if (
        readiness_status == "ready_for_publish_package"
        and output.publishing_readiness.missing_required_metadata
    ):
        raise RuntimeError("ready publish package cannot include missing metadata")

    if readiness_status == "ready_for_publish_package":
        if not final_edit_context_supplied:
            raise RuntimeError("ready publish package requires final edit context")
        if unresolved_qc or output.publishing_readiness.unresolved_qc_issues:
            raise RuntimeError("ready publish package cannot include unresolved QC")
        _require_publish_options(output)
        if output.recommended_options is not None:
            _validate_recommended_publish_options(output)

    _validate_platform_copy_scope(
        output.platform_copy_options,
        request_context.get("requested_platforms") or [],
    )
    _validate_no_publish_claims(output.model_dump())


def _require_publish_options(output: PublishPackage) -> None:
    required_collections = {
        "title_options": output.title_options,
        "seo_keyword_options": output.seo_keyword_options,
        "caption_options": output.caption_options,
        "description_options": output.description_options,
        "hashtag_options": output.hashtag_options,
        "platform_copy_options": output.platform_copy_options,
    }
    missing = [
        name for name, collection in required_collections.items() if not collection
    ]
    if missing:
        raise RuntimeError(
            "ready publish package missing option collections: "
            + ", ".join(sorted(missing))
        )


def _validate_recommended_publish_options(output: PublishPackage) -> None:
    recommendations = output.recommended_options
    if recommendations is None:
        return

    option_ids = {
        "title": {item.option_id for item in output.title_options},
        "caption": {item.option_id for item in output.caption_options},
        "description": {item.option_id for item in output.description_options},
        "hashtag": {item.option_id for item in output.hashtag_options},
    }
    if recommendations.title_option_id not in option_ids["title"]:
        raise RuntimeError("recommended title option does not exist")
    if recommendations.caption_option_id not in option_ids["caption"]:
        raise RuntimeError("recommended caption option does not exist")
    if recommendations.description_option_id not in option_ids["description"]:
        raise RuntimeError("recommended description option does not exist")
    if recommendations.hashtag_option_id not in option_ids["hashtag"]:
        raise RuntimeError("recommended hashtag option does not exist")


def _validate_platform_copy_scope(
    platform_copy_options: list[PlatformCopyOption],
    requested_platforms: list[Any],
) -> None:
    requested = {
        str(platform).strip().lower()
        for platform in requested_platforms
        if str(platform or "").strip()
    }
    generic = {variant.lower() for variant in GENERIC_PLATFORM_VARIANTS}
    for option in platform_copy_options:
        platform_variant = option.platform_variant.strip().lower()
        if not platform_variant:
            raise RuntimeError("platform copy option requires platform_variant")
        if platform_variant in generic:
            continue
        if platform_variant not in requested:
            raise RuntimeError(
                "PUBLISH output named a platform the creator did not request"
            )


def _validate_no_publish_claims(value: Any) -> None:
    claim_patterns = (
        r"\b(has been|was|is|successfully|already)\s+published\b",
        r"\b(has been|was|is|successfully|already)\s+posted\b",
        r"\b(has been|was|is|successfully|already)\s+scheduled\b",
        r"\b(has been|was|is|successfully|already)\s+uploaded\b",
        r"\b(content|video|post|media)\s+(is|was|has been)\s+live\b",
        r"\b(published|posted|scheduled|uploaded)\s+(to|on)\b",
        r"\bstudio//one\s+(published|posted|scheduled|uploaded|authenticated)\b",
        r"\bclick(ed)?\s+publish\b",
    )
    for text in _string_values(value):
        normalized = text.strip().lower()
        if any(re.search(pattern, normalized) for pattern in claim_patterns):
            raise RuntimeError(
                "PUBLISH package claimed content was published, posted, uploaded, scheduled, or live"
            )


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


async def run_post_production_agent(project_id: str) -> dict[str, Any]:
    """Run POST PRODUCTION to prepare request-scoped editing instructions."""
    if not project_id.strip():
        raise ValueError("project_id is required")

    async def retrieve_post_production_stage_memory() -> dict[str, Any]:
        return await retrieve_post_production_memory_bundle(project_id=project_id)

    preflight = await retrieve_post_production_stage_memory()
    _require_post_production_memory(preflight.get("production_memory"), project_id)

    report = await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.POST_PRODUCTION,
        output_schema=PostProductionPackage,
        user_message_text=(
            "Prepare the POST PRODUCTION editing package from MCP-retrieved "
            "approved storyboard, approved assets, QC provenance, and creator "
            "decision history. Do not edit, render, upload, publish, or mutate "
            "production state."
        ),
        memory_retriever=retrieve_post_production_stage_memory,
    )
    _require_post_production_memory(report.get("production_memory"), project_id)
    _validate_post_production_package(report)
    report["validation"].update(
        {
            "approved_storyboard_required": True,
            "approved_assets_only": True,
            "agent_memory_retrieval_path": "official_mcp_clickhouse",
            "post_production_package_persistence": "request_scoped",
            "external_editor_operated": False,
            "video_rendered": False,
            "timeline_manipulated": False,
            "editing_software_upload_performed": False,
            "publish_performed": False,
            "clickhouse_writes_performed": False,
        }
    )
    return report


async def run_publish_agent(
    project_id: str,
    final_edit_reference: str | None = None,
    final_edit_is_complete: bool = False,
    final_edit_notes: str = "",
    required_metadata: dict[str, Any] | None = None,
    requested_platforms: list[str] | None = None,
    post_production_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run PUBLISH to prepare a request-scoped creator publishing package."""
    if not project_id.strip():
        raise ValueError("project_id is required")

    async def retrieve_publish_stage_memory() -> dict[str, Any]:
        return await retrieve_publish_memory_bundle(project_id=project_id)

    preflight = await retrieve_publish_stage_memory()
    _require_publish_memory(preflight.get("production_memory"), project_id)

    request_context = {
        "final_edit_reference": final_edit_reference.strip()
        if final_edit_reference
        else None,
        "final_edit_is_complete": bool(final_edit_is_complete),
        "final_edit_notes": final_edit_notes.strip(),
        "required_metadata": required_metadata or {},
        "requested_platforms": [
            platform.strip()
            for platform in requested_platforms or []
            if platform.strip()
        ],
        "post_production_package_supplied": post_production_package is not None,
    }
    request_context_text = json.dumps(
        {
            **request_context,
            "post_production_package": post_production_package,
        },
        sort_keys=True,
        default=str,
    )

    report = await _run_stage_agent(
        project_id=project_id,
        stage=StudioOneStage.PUBLISH,
        output_schema=PublishPackage,
        user_message_text=(
            "Prepare the PUBLISH package from MCP-retrieved approved production "
            "state and this request-scoped creator context. Do not authenticate, "
            "call publishing APIs, upload, schedule, post, claim live status, or "
            "mutate production state.\n"
            f"Request-scoped creator context: {request_context_text}"
        ),
        memory_retriever=retrieve_publish_stage_memory,
    )
    report["request_context"] = request_context
    _require_publish_memory(report.get("production_memory"), project_id)
    _validate_publish_package(report)
    report["validation"].update(
        {
            "approved_storyboard_required": True,
            "agent_memory_retrieval_path": "official_mcp_clickhouse",
            "publish_package_persistence": "request_scoped",
            "post_production_package_persistence_required": False,
            "external_publishing_api_called": False,
            "social_platform_auth_performed": False,
            "media_upload_performed": False,
            "content_scheduled": False,
            "content_published": False,
            "clickhouse_writes_performed": False,
            "non_google_ai_runtime_integration_added": False,
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
