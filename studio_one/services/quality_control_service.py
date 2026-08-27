"""QUALITY CONTROL orchestration and creator decision handling."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel
from pydantic import Field

from studio_one.agents.refinement_agent import run_quality_control_agent
from studio_one.integrations.clickhouse_persistence import (
    ClickHouseQualityControlPersistence,
    CreatedQualityControlReviewRecord,
    CreatorQualityControlDecisionRecord,
    QualityControlDecisionResult,
    QualityControlReviewRecord,
)
from studio_one.workflow.stages import StudioOneStage


class QualityControlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    external_asset_candidate_id: str = Field(min_length=1)


class QualityControlResult(BaseModel):
    project_id: str
    stage: str
    assessment: dict[str, Any]
    review: dict[str, Any]


class QualityControlDecisionRequest(BaseModel):
    project_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    action: str = Field(pattern="^(approve|reject|needs_revision)$")
    decided_by: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    reviewer_identity_source: str = Field(min_length=1)


class QualityControlRunner(Protocol):
    def __call__(
        self,
        *,
        project_id: str,
        external_asset_candidate_id: str,
    ) -> Awaitable[dict[str, Any]]:
        """Run the Gemini QC assessment."""


class QualityControlWriter(Protocol):
    def create_asset_qc_review(
        self,
        record: QualityControlReviewRecord,
    ) -> CreatedQualityControlReviewRecord:
        """Persist a pending human review for an AI QC recommendation."""

    def decide_asset_qc_review(
        self,
        record: CreatorQualityControlDecisionRecord,
    ) -> QualityControlDecisionResult:
        """Apply an explicit human QC decision."""


class QualityControlService:
    def __init__(
        self,
        writer: QualityControlWriter,
        quality_control_runner: QualityControlRunner = run_quality_control_agent,
    ) -> None:
        self._writer = writer
        self._quality_control_runner = quality_control_runner

    async def run_quality_control(
        self,
        request: QualityControlRequest,
    ) -> QualityControlResult:
        report = await self._quality_control_runner(
            project_id=request.project_id,
            external_asset_candidate_id=request.external_asset_candidate_id,
        )
        runtime = report.get("runtime") or {}
        assessment = report["structured_output"]
        review = self._writer.create_asset_qc_review(
            QualityControlReviewRecord(
                project_id=request.project_id,
                external_asset_candidate_id=request.external_asset_candidate_id,
                assessment=assessment,
                source_reference="quality_control_agent",
                source_version="",
                evidence_references=("mcp:qc-memory",),
                gemini_model=str(runtime.get("gemini_model_used") or ""),
                gemini_response_id=str(runtime.get("gemini_response_id") or ""),
                gemini_prompt_version="quality_control:v1",
            )
        )
        return QualityControlResult(
            project_id=request.project_id,
            stage=StudioOneStage.QUALITY_CONTROL.value,
            assessment=report,
            review=asdict(review),
        )

    def decide_quality_control_review(
        self,
        request: QualityControlDecisionRequest,
    ) -> dict[str, Any]:
        result = self._writer.decide_asset_qc_review(
            CreatorQualityControlDecisionRecord(
                project_id=request.project_id,
                review_id=request.review_id,
                action=request.action,  # type: ignore[arg-type]
                decided_by=request.decided_by,
                decision_reason=request.decision_reason,
                reviewer_identity_source=request.reviewer_identity_source,
            )
        )
        return asdict(result)


def build_quality_control_service() -> QualityControlService:
    return QualityControlService(writer=ClickHouseQualityControlPersistence())
