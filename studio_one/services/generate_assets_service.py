"""Provider-neutral GENERATE ASSETS orchestration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel
from pydantic import Field

from studio_one.agents.refinement_agent import run_generate_assets_agent
from studio_one.integrations.clickhouse_persistence import (
    ClickHouseGenerationPackagePersistence,
    CreatedGenerationPackageRecord,
    GenerationPackageCreateRecord,
)
from studio_one.workflow.stages import StudioOneStage


class GenerateAssetsRequest(BaseModel):
    project_id: str = Field(min_length=1)


class GenerateAssetsResult(BaseModel):
    project_id: str
    stage: str
    package: dict[str, Any]
    persisted_generation_packages: list[dict[str, Any]]


GenerateAssetsRunner = Callable[..., Awaitable[dict[str, Any]]]


class GenerationPackageWriter(Protocol):
    def persist_generate_assets_package(
        self,
        record: GenerationPackageCreateRecord,
    ) -> list[CreatedGenerationPackageRecord]:
        """Persist versioned generation prompt and handoff instructions."""


class GenerateAssetsService:
    def __init__(
        self,
        generate_assets_runner: GenerateAssetsRunner = run_generate_assets_agent,
        generation_package_writer: GenerationPackageWriter | None = None,
    ) -> None:
        self._generate_assets_runner = generate_assets_runner
        self._generation_package_writer = generation_package_writer

    async def generate_assets_package(
        self,
        request: GenerateAssetsRequest,
    ) -> GenerateAssetsResult:
        package = await self._generate_assets_runner(project_id=request.project_id)
        persisted_generation_packages: list[dict[str, Any]] = []
        if self._generation_package_writer is not None:
            runtime = package.get("runtime") or {}
            persisted = self._generation_package_writer.persist_generate_assets_package(
                GenerationPackageCreateRecord(
                    project_id=request.project_id,
                    package=package,
                    source_reference="generate_assets_agent",
                    source_version="",
                    evidence_references=("mcp:project-memory",),
                    gemini_model=str(runtime.get("gemini_model_used") or ""),
                    gemini_response_id=str(runtime.get("gemini_response_id") or ""),
                    gemini_prompt_version="generate_assets:v1",
                )
            )
            persisted_generation_packages = [asdict(row) for row in persisted]
        return GenerateAssetsResult(
            project_id=request.project_id,
            stage=StudioOneStage.GENERATE_ASSETS.value,
            package=package,
            persisted_generation_packages=persisted_generation_packages,
        )


def build_generate_assets_service() -> GenerateAssetsService:
    return GenerateAssetsService(
        generate_assets_runner=run_generate_assets_agent,
        generation_package_writer=ClickHouseGenerationPackagePersistence(),
    )
