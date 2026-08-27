"""Storyboard review and creator approval orchestration."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel
from pydantic import Field

from studio_one.config import StudioOneConfig
from studio_one.integrations.clickhouse_persistence import (
    ClickHouseStoryboardPersistence,
    CreatedStoryboardReviewRecord,
    CreatorStoryboardDecisionRecord,
    StoryboardCandidateReviewRecord,
    StoryboardReviewDecisionResult,
)


class SubmitStoryboardCandidateReviewRequest(BaseModel):
    project_id: str = Field(min_length=1)
    storyboard_candidate: dict[str, Any]
    source_reference: str = ""
    source_version: str = ""
    evidence_references: list[str] = Field(default_factory=list)
    gemini_model: str = ""
    gemini_response_id: str = ""
    gemini_prompt_version: str = ""
    confidence: float = 0.0
    recommendation_version: int = 1
    supersedes_review_id: str | None = None


class DecideStoryboardReviewRequest(BaseModel):
    project_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    action: Literal["approve", "reject", "needs_revision"]
    decided_by: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    reviewer_identity_source: str = Field(min_length=1)


class StoryboardReviewPersistence(Protocol):
    def create_storyboard_candidate_review(
        self,
        record: StoryboardCandidateReviewRecord,
    ) -> CreatedStoryboardReviewRecord:
        """Persist a storyboard candidate as a pending review."""

    def decide_storyboard_review(
        self,
        record: CreatorStoryboardDecisionRecord,
    ) -> StoryboardReviewDecisionResult:
        """Apply an explicit human decision to a storyboard review."""


class StoryboardService:
    def __init__(self, persistence: StoryboardReviewPersistence) -> None:
        self._persistence = persistence

    def submit_candidate_for_review(
        self,
        request: SubmitStoryboardCandidateReviewRequest,
    ) -> CreatedStoryboardReviewRecord:
        return self._persistence.create_storyboard_candidate_review(
            StoryboardCandidateReviewRecord(
                project_id=request.project_id,
                storyboard_candidate=request.storyboard_candidate,
                source_reference=request.source_reference,
                source_version=request.source_version,
                evidence_references=tuple(request.evidence_references),
                gemini_model=request.gemini_model,
                gemini_response_id=request.gemini_response_id,
                gemini_prompt_version=request.gemini_prompt_version,
                confidence=request.confidence,
                recommendation_version=request.recommendation_version,
                supersedes_review_id=request.supersedes_review_id,
            )
        )

    def decide_review(
        self,
        request: DecideStoryboardReviewRequest,
    ) -> StoryboardReviewDecisionResult:
        return self._persistence.decide_storyboard_review(
            CreatorStoryboardDecisionRecord(
                project_id=request.project_id,
                review_id=request.review_id,
                action=request.action,
                decided_by=request.decided_by,
                decision_reason=request.decision_reason,
                reviewer_identity_source=request.reviewer_identity_source,
            )
        )


def build_storyboard_service(
    config: StudioOneConfig | None = None,
) -> StoryboardService:
    return StoryboardService(
        persistence=ClickHouseStoryboardPersistence(config=config),
    )
