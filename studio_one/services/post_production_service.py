"""Provider-neutral POST PRODUCTION orchestration."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel
from pydantic import Field

from studio_one.agents.refinement_agent import run_post_production_agent
from studio_one.workflow.stages import StudioOneStage


class PostProductionRequest(BaseModel):
    project_id: str = Field(min_length=1)


class PostProductionResult(BaseModel):
    project_id: str
    stage: str
    package: dict[str, Any]


PostProductionRunner = Callable[..., Awaitable[dict[str, Any]]]


class PostProductionService:
    def __init__(
        self,
        post_production_runner: PostProductionRunner = run_post_production_agent,
    ) -> None:
        self._post_production_runner = post_production_runner

    async def prepare_editing_package(
        self,
        request: PostProductionRequest,
    ) -> PostProductionResult:
        package = await self._post_production_runner(project_id=request.project_id)
        return PostProductionResult(
            project_id=request.project_id,
            stage=StudioOneStage.POST_PRODUCTION.value,
            package=package,
        )


def build_post_production_service() -> PostProductionService:
    return PostProductionService(post_production_runner=run_post_production_agent)
