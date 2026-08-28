"""Provider-neutral PUBLISH orchestration."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel
from pydantic import Field

from studio_one.agents.refinement_agent import run_publish_agent
from studio_one.workflow.stages import StudioOneStage


class PublishRequest(BaseModel):
    project_id: str = Field(min_length=1)
    final_edit_reference: str | None = None
    final_edit_is_complete: bool = False
    final_edit_notes: str = ""
    required_metadata: dict[str, Any] = Field(default_factory=dict)
    requested_platforms: list[str] = Field(default_factory=list)
    post_production_package: dict[str, Any] | None = None


class PublishResult(BaseModel):
    project_id: str
    stage: str
    package: dict[str, Any]


PublishRunner = Callable[..., Awaitable[dict[str, Any]]]


class PublishService:
    def __init__(
        self,
        publish_runner: PublishRunner = run_publish_agent,
    ) -> None:
        self._publish_runner = publish_runner

    async def prepare_publish_package(
        self,
        request: PublishRequest,
    ) -> PublishResult:
        package = await self._publish_runner(
            project_id=request.project_id,
            final_edit_reference=request.final_edit_reference,
            final_edit_is_complete=request.final_edit_is_complete,
            final_edit_notes=request.final_edit_notes,
            required_metadata=request.required_metadata,
            requested_platforms=request.requested_platforms,
            post_production_package=request.post_production_package,
        )
        return PublishResult(
            project_id=request.project_id,
            stage=StudioOneStage.PUBLISH.value,
            package=package,
        )


def build_publish_service() -> PublishService:
    return PublishService(publish_runner=run_publish_agent)
