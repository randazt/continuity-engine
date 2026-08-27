"""Creator-controlled external asset intake for future QUALITY CONTROL."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from pydantic import BaseModel
from pydantic import Field

from studio_one.integrations.clickhouse_persistence import (
    ClickHouseExternalAssetIntakePersistence,
    CreatedExternalAssetCandidateRecord,
    ExternalAssetIntakeRecord,
)
from studio_one.workflow.stages import StudioOneStage


class ExternalAssetIntakeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    approved_storyboard_id: str = Field(min_length=1)
    approved_storyboard_version: int = Field(ge=1)
    storyboard_panel_shot_reference: str = Field(min_length=1)
    asset_type: str = Field(min_length=1)
    external_asset_reference: str = Field(min_length=1)
    submitted_by: str = Field(min_length=1)
    source_generation_package_id: str | None = None
    source_generation_package_version: int = 0
    creator_supplied_metadata: dict[str, Any] = Field(default_factory=dict)
    source_reference: str = ""
    source_version: str = ""
    evidence_references: list[str] = Field(default_factory=list)
    supersedes_external_asset_candidate_id: str | None = None
    retry_of_external_asset_candidate_id: str | None = None


class ExternalAssetIntakeResult(BaseModel):
    project_id: str
    stage: str
    candidate: dict[str, Any]


class ExternalAssetIntakeWriter(Protocol):
    def submit_external_asset_candidate(
        self,
        record: ExternalAssetIntakeRecord,
    ) -> CreatedExternalAssetCandidateRecord:
        """Persist an external asset candidate without approving it."""


class ExternalAssetIntakeService:
    def __init__(self, writer: ExternalAssetIntakeWriter) -> None:
        self._writer = writer

    def submit_candidate_for_qc(
        self,
        request: ExternalAssetIntakeRequest,
    ) -> ExternalAssetIntakeResult:
        candidate = self._writer.submit_external_asset_candidate(
            ExternalAssetIntakeRecord(
                project_id=request.project_id,
                source_generation_package_id=request.source_generation_package_id,
                source_generation_package_version=(
                    request.source_generation_package_version
                ),
                approved_storyboard_id=request.approved_storyboard_id,
                approved_storyboard_version=request.approved_storyboard_version,
                storyboard_panel_shot_reference=(
                    request.storyboard_panel_shot_reference
                ),
                asset_type=request.asset_type,
                external_asset_reference=request.external_asset_reference,
                creator_supplied_metadata=request.creator_supplied_metadata,
                source_reference=request.source_reference,
                source_version=request.source_version,
                evidence_references=tuple(request.evidence_references),
                submitted_by=request.submitted_by,
                supersedes_external_asset_candidate_id=(
                    request.supersedes_external_asset_candidate_id
                ),
                retry_of_external_asset_candidate_id=(
                    request.retry_of_external_asset_candidate_id
                ),
            )
        )
        return ExternalAssetIntakeResult(
            project_id=request.project_id,
            stage=StudioOneStage.QUALITY_CONTROL.value,
            candidate=asdict(candidate),
        )


def build_external_asset_intake_service() -> ExternalAssetIntakeService:
    return ExternalAssetIntakeService(
        writer=ClickHouseExternalAssetIntakePersistence()
    )
