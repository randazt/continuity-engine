"""Project setup and creator-controlled early workflow orchestration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel
from pydantic import Field

from studio_one.agents.refinement_agent import run_brainstorm_agent
from studio_one.agents.refinement_agent import run_finalize_storyboard_agent
from studio_one.agents.refinement_agent import run_refine_agent
from studio_one.config import StudioOneConfig
from studio_one.integrations.clickhouse_persistence import (
    ClickHouseProjectPersistence,
    CreatedProjectRecord,
    ProjectCreateRecord,
    ProjectTitleUpdateRecord,
    UpdatedProjectTitleRecord,
)
from studio_one.workflow.stages import StudioOneStage
from studio_one.workflow.transitions import require_creator_action_transition


class CreateProjectRequest(BaseModel):
    initial_creative_intent: str = Field(min_length=1)
    production_constraints: str = ""
    source_reference: str = "creator_project_creation_request"
    source_version: str = ""


class CreateProjectAndBrainstormResult(BaseModel):
    project: dict[str, Any]
    stage: str
    brainstorm: dict[str, Any]


class WorkingTitleSelectionRequest(BaseModel):
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)


class WorkingTitleSelectionResult(BaseModel):
    project_id: str
    title: str
    title_status: str
    authority_level: str
    approval_status: str
    asset_created: bool
    storyboard_approval_created: bool
    canon_approval_created: bool


class RefineProjectRequest(BaseModel):
    project_id: str = Field(min_length=1)
    creator_direction: str = Field(min_length=1)


class RefineProjectResult(BaseModel):
    project_id: str
    stage: str
    refinement: dict[str, Any]


class FinalizeStoryboardRequest(BaseModel):
    project_id: str = Field(min_length=1)
    creator_action: str = Field(min_length=1)
    target_total_runtime: str = ""


class FinalizeStoryboardResult(BaseModel):
    project_id: str
    stage: str
    storyboard_candidate: dict[str, Any]


class ProjectWriter(Protocol):
    def create_project(self, record: ProjectCreateRecord) -> CreatedProjectRecord:
        """Persist a project row and return the created record."""

    def update_project_title(
        self,
        record: ProjectTitleUpdateRecord,
    ) -> UpdatedProjectTitleRecord:
        """Persist creator-selected working title metadata."""


BrainstormRunner = Callable[..., Awaitable[dict[str, Any]]]
RefineRunner = Callable[..., Awaitable[dict[str, Any]]]
StoryboardRunner = Callable[..., Awaitable[dict[str, Any]]]


class ProjectService:
    def __init__(
        self,
        project_writer: ProjectWriter,
        brainstorm_runner: BrainstormRunner = run_brainstorm_agent,
        refine_runner: RefineRunner = run_refine_agent,
        storyboard_runner: StoryboardRunner = run_finalize_storyboard_agent,
    ) -> None:
        self._project_writer = project_writer
        self._brainstorm_runner = brainstorm_runner
        self._refine_runner = refine_runner
        self._storyboard_runner = storyboard_runner

    async def create_project_and_start_brainstorm(
        self,
        request: CreateProjectRequest,
    ) -> CreateProjectAndBrainstormResult:
        created_project = self._project_writer.create_project(
            ProjectCreateRecord(
                title="",
                initial_creative_intent=request.initial_creative_intent,
                production_constraints=request.production_constraints,
                source_reference=request.source_reference,
                source_version=request.source_version,
            )
        )

        brainstorm = await self._brainstorm_runner(
            project_id=created_project.project_id,
        )

        return CreateProjectAndBrainstormResult(
            project=asdict(created_project),
            stage=StudioOneStage.BRAINSTORM.value,
            brainstorm=brainstorm,
        )

    def select_working_title(
        self,
        request: WorkingTitleSelectionRequest,
    ) -> WorkingTitleSelectionResult:
        updated = self._project_writer.update_project_title(
            ProjectTitleUpdateRecord(
                project_id=request.project_id,
                title=request.title,
            )
        )
        return WorkingTitleSelectionResult(
            project_id=updated.project_id,
            title=updated.title,
            title_status="creator_selected_working_title",
            authority_level="creator_supplied_project_metadata",
            approval_status="creator_supplied",
            asset_created=False,
            storyboard_approval_created=False,
            canon_approval_created=False,
        )

    async def refine_project(
        self,
        request: RefineProjectRequest,
    ) -> RefineProjectResult:
        require_creator_action_transition(
            current_stage=StudioOneStage.BRAINSTORM,
            requested_stage=StudioOneStage.REFINE,
            creator_action=request.creator_direction,
        )

        refinement = await self._refine_runner(
            project_id=request.project_id,
            creator_direction=request.creator_direction,
        )

        return RefineProjectResult(
            project_id=request.project_id,
            stage=StudioOneStage.REFINE.value,
            refinement=refinement,
        )

    async def finalize_storyboard_candidate(
        self,
        request: FinalizeStoryboardRequest,
    ) -> FinalizeStoryboardResult:
        require_creator_action_transition(
            current_stage=StudioOneStage.REFINE,
            requested_stage=StudioOneStage.FINALIZE_STORYBOARD,
            creator_action=request.creator_action,
        )

        storyboard = await self._storyboard_runner(
            project_id=request.project_id,
            creator_action=request.creator_action,
            target_total_runtime=request.target_total_runtime or None,
        )

        return FinalizeStoryboardResult(
            project_id=request.project_id,
            stage=StudioOneStage.FINALIZE_STORYBOARD.value,
            storyboard_candidate=storyboard,
        )


def build_project_service(
    config: StudioOneConfig | None = None,
) -> ProjectService:
    return ProjectService(
        project_writer=ClickHouseProjectPersistence(config=config),
        brainstorm_runner=run_brainstorm_agent,
        refine_runner=run_refine_agent,
        storyboard_runner=run_finalize_storyboard_agent,
    )
