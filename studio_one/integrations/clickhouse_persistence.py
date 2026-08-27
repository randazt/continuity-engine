"""Direct ClickHouse application persistence for controlled writes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL
from uuid import UUID
from uuid import uuid4
from uuid import uuid5

import clickhouse_connect
from google.cloud import secretmanager

from studio_one.config import StudioOneConfig


PROJECT_COLUMNS = [
    "project_id",
    "title",
    "status",
    "current_canon_version",
    "authority_level",
    "authoritative_source",
    "source_reference",
    "source_version",
    "approval_status",
    "state_version",
    "approved_decision_id",
    "production_constraints",
    "initial_creative_intent",
]

REVIEW_QUEUE_COLUMNS = [
    "review_id",
    "project_id",
    "asset_id",
    "review_type",
    "proposed_action",
    "finding",
    "rationale",
    "source_reference",
    "confidence",
    "severity",
    "status",
    "reviewer",
    "reviewer_notes",
    "created_at",
    "reviewed_at",
    "authority_level",
    "authoritative_source",
    "source_version",
    "evidence_references",
    "qc_layer",
    "qc_type",
    "gemini_model",
    "gemini_response_id",
    "gemini_prompt_version",
    "proposed_state_change",
    "recommendation_version",
    "supersedes_review_id",
]

DECISION_LOG_COLUMNS = [
    "decision_id",
    "project_id",
    "review_id",
    "asset_id",
    "decision",
    "decided_by",
    "decision_reason",
    "previous_state",
    "resulting_state",
    "agent_recommendation",
    "agent_confidence",
    "source_reference",
    "decided_at",
    "authority_level",
    "reviewer_identity_source",
    "affected_table",
    "affected_state_version",
    "resulting_state_version",
]

STORYBOARD_COLUMNS = [
    "storyboard_id",
    "project_id",
    "storyboard_version",
    "status",
    "approval_status",
    "authority_level",
    "title",
    "target_total_runtime",
    "creative_narrative_objective",
    "production_constraints_applied",
    "unresolved_issues",
    "storyboard_json",
    "storyboard_schema_version",
    "source_reference",
    "source_version",
    "authoritative_source",
    "approved_decision_id",
    "approved_review_id",
    "approved_by",
    "reviewer_identity_source",
    "approved_at",
    "created_at",
    "supersedes_storyboard_id",
]

GENERATION_PACKAGE_COLUMNS = [
    "generation_package_id",
    "project_id",
    "approved_storyboard_id",
    "approved_storyboard_version",
    "storyboard_panel_shot_reference",
    "package_type",
    "package_version",
    "status",
    "authority_level",
    "package_json",
    "package_schema_version",
    "source_reference",
    "source_version",
    "evidence_references",
    "gemini_model",
    "gemini_response_id",
    "gemini_prompt_version",
    "created_by",
    "created_at",
    "supersedes_generation_package_id",
]

EXTERNAL_ASSET_INTAKE_COLUMNS = [
    "external_asset_candidate_id",
    "project_id",
    "source_generation_package_id",
    "source_generation_package_version",
    "approved_storyboard_id",
    "approved_storyboard_version",
    "storyboard_panel_shot_reference",
    "asset_type",
    "external_asset_reference",
    "creator_supplied_metadata_json",
    "intake_status",
    "qc_status",
    "authority_level",
    "source_reference",
    "source_version",
    "evidence_references",
    "submitted_by",
    "submitted_at",
    "supersedes_external_asset_candidate_id",
    "retry_of_external_asset_candidate_id",
]

ASSET_COLUMNS = [
    "asset_id",
    "project_id",
    "asset_type",
    "name",
    "description",
    "continuity_status",
    "canon_version",
    "source_reference",
    "created_at",
    "updated_at",
    "authority_level",
    "authoritative_source",
    "source_version",
    "approval_status",
    "state_version",
    "approved_decision_id",
    "reuse_source_asset_id",
    "reuse_relationship",
    "source_generation_package_id",
    "source_generation_package_version",
    "external_asset_candidate_id",
    "external_asset_reference",
    "external_asset_metadata_json",
]

STORYBOARD_SCHEMA_VERSION = "storyboard_candidate:v1"
GENERATION_PACKAGE_SCHEMA_VERSION = "generation_package:v1"
GENERATION_PACKAGE_STATUS = "instructions_for_creator"
GENERATION_PACKAGE_AUTHORITY_LEVEL = "production_instruction"
EXTERNAL_ASSET_INTAKE_STATUS = "submitted_for_qc"
EXTERNAL_ASSET_QC_STATUS = "pending_qc"
EXTERNAL_ASSET_AUTHORITY_LEVEL = "external_asset_candidate"
QC_REVIEW_PENDING_STATUS = "qc_review_pending_human_decision"
QC_APPROVED_FOR_PROMOTION_STATUS = "approved_for_promotion"
EXTERNAL_ASSET_PROMOTED_STATUS = "promoted_to_assets"
QC_REVIEW_TYPE = "asset_qc"
QC_RECOMMENDATION_ACTIONS = {
    "recommend_approve": "approve_asset",
    "recommend_reject": "reject_asset",
    "recommend_revision": "request_revision",
}
QC_DECISION_VALUES = {
    "approve": "approved",
    "reject": "rejected",
    "needs_revision": "needs_revision",
}
STORYBOARD_DECISION_VALUES = {
    "approve": "approved",
    "reject": "rejected",
    "needs_revision": "needs_revision",
}


@dataclass(frozen=True)
class ProjectCreateRecord:
    title: str
    initial_creative_intent: str
    production_constraints: str = ""
    source_reference: str = "creator_project_creation_request"
    source_version: str = ""


@dataclass(frozen=True)
class CreatedProjectRecord:
    project_id: str
    title: str
    status: str
    current_canon_version: str
    authority_level: str
    authoritative_source: str
    source_reference: str
    source_version: str
    approval_status: str
    state_version: int
    approved_decision_id: None
    production_constraints: str
    initial_creative_intent: str


@dataclass(frozen=True)
class StoryboardCandidateReviewRecord:
    project_id: str
    storyboard_candidate: dict[str, Any]
    source_reference: str = ""
    source_version: str = ""
    evidence_references: tuple[str, ...] = ()
    gemini_model: str = ""
    gemini_response_id: str = ""
    gemini_prompt_version: str = ""
    confidence: float = 0.0
    recommendation_version: int = 1
    supersedes_review_id: str | None = None


@dataclass(frozen=True)
class CreatedStoryboardReviewRecord:
    review_id: str
    project_id: str
    status: str
    review_type: str
    proposed_action: str
    proposed_state_change: str


@dataclass(frozen=True)
class CreatorStoryboardDecisionRecord:
    project_id: str
    review_id: str
    action: Literal["approve", "reject", "needs_revision"]
    decided_by: str
    decision_reason: str
    reviewer_identity_source: str


@dataclass(frozen=True)
class StoryboardReviewDecisionResult:
    project_id: str
    review_id: str
    decision_id: str
    decision: str
    review_status: str
    storyboard_id: str | None = None
    storyboard_version: int | None = None
    storyboard_created: bool = False


@dataclass(frozen=True)
class GenerationPackageCreateRecord:
    project_id: str
    package: dict[str, Any]
    source_reference: str = "generate_assets_agent"
    source_version: str = ""
    evidence_references: tuple[str, ...] = ()
    gemini_model: str = ""
    gemini_response_id: str = ""
    gemini_prompt_version: str = "generate_assets:v1"
    created_by: str = "studio_one"


@dataclass(frozen=True)
class CreatedGenerationPackageRecord:
    generation_package_id: str
    project_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int
    storyboard_panel_shot_reference: str
    package_type: str
    package_version: int
    status: str
    authority_level: str
    package_json: str
    supersedes_generation_package_id: str | None


@dataclass(frozen=True)
class ExternalAssetIntakeRecord:
    project_id: str
    approved_storyboard_id: str
    approved_storyboard_version: int
    storyboard_panel_shot_reference: str
    asset_type: str
    external_asset_reference: str
    submitted_by: str
    source_generation_package_id: str | None = None
    source_generation_package_version: int = 0
    creator_supplied_metadata: dict[str, Any] | None = None
    source_reference: str = ""
    source_version: str = ""
    evidence_references: tuple[str, ...] = ()
    supersedes_external_asset_candidate_id: str | None = None
    retry_of_external_asset_candidate_id: str | None = None


@dataclass(frozen=True)
class CreatedExternalAssetCandidateRecord:
    external_asset_candidate_id: str
    project_id: str
    source_generation_package_id: str | None
    source_generation_package_version: int
    approved_storyboard_id: str
    approved_storyboard_version: int
    storyboard_panel_shot_reference: str
    asset_type: str
    external_asset_reference: str
    intake_status: str
    qc_status: str
    authority_level: str
    supersedes_external_asset_candidate_id: str | None
    retry_of_external_asset_candidate_id: str | None


@dataclass(frozen=True)
class QualityControlReviewRecord:
    project_id: str
    external_asset_candidate_id: str
    assessment: dict[str, Any]
    source_reference: str = "quality_control_agent"
    source_version: str = ""
    evidence_references: tuple[str, ...] = ()
    gemini_model: str = ""
    gemini_response_id: str = ""
    gemini_prompt_version: str = "quality_control:v1"
    recommendation_version: int = 1


@dataclass(frozen=True)
class CreatedQualityControlReviewRecord:
    review_id: str
    project_id: str
    external_asset_candidate_id: str
    status: str
    review_type: str
    proposed_action: str
    proposed_state_change: str
    review_created: bool = True


@dataclass(frozen=True)
class CreatorQualityControlDecisionRecord:
    project_id: str
    review_id: str
    action: Literal["approve", "reject", "needs_revision"]
    decided_by: str
    decision_reason: str
    reviewer_identity_source: str


@dataclass(frozen=True)
class QualityControlDecisionResult:
    project_id: str
    review_id: str
    external_asset_candidate_id: str
    decision_id: str
    decision: str
    review_status: str
    candidate_qc_status: str
    candidate_intake_status: str
    asset_id: str | None = None
    asset_created: bool = False


class StoryboardApprovalPartialFailure(RuntimeError):
    """Raised when a non-transactional approval write needs retry/recovery."""


class QualityControlPartialFailure(RuntimeError):
    """Raised when non-transactional QC writes need safe retry/recovery."""


class ClickHouseClient(Protocol):
    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str],
        database: str | None = None,
    ) -> Any:
        """Insert rows into ClickHouse."""

    def query(self, query: str) -> Any:
        """Query ClickHouse."""

    def command(self, command: str) -> Any:
        """Run a ClickHouse command."""


ClickHouseInsertClient = ClickHouseClient


def get_clickhouse_password(config: StudioOneConfig | None = None) -> str:
    runtime_config = config or StudioOneConfig.from_env()
    client = secretmanager.SecretManagerServiceClient()
    name = (
        f"projects/{runtime_config.google_cloud_project}/secrets/"
        f"{runtime_config.clickhouse_password_secret}/versions/latest"
    )
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def build_clickhouse_client(
    config: StudioOneConfig | None = None,
) -> ClickHouseInsertClient:
    runtime_config = config or StudioOneConfig.from_env()
    return clickhouse_connect.get_client(
        host=runtime_config.clickhouse_host,
        port=runtime_config.clickhouse_port,
        username=runtime_config.clickhouse_user,
        password=get_clickhouse_password(runtime_config),
        database=runtime_config.clickhouse_database,
        secure=runtime_config.clickhouse_secure,
        verify=runtime_config.clickhouse_verify,
    )


class ClickHouseProjectPersistence:
    """Application-owned writer for new project records."""

    def __init__(
        self,
        client: ClickHouseInsertClient | None = None,
        config: StudioOneConfig | None = None,
    ) -> None:
        self._config = config or StudioOneConfig.from_env()
        self._client = client or build_clickhouse_client(self._config)

    def create_project(self, record: ProjectCreateRecord) -> CreatedProjectRecord:
        title = record.title.strip()
        if not title:
            raise ValueError("project title is required")
        initial_creative_intent = record.initial_creative_intent.strip()
        if not initial_creative_intent:
            raise ValueError("initial_creative_intent is required")

        created = CreatedProjectRecord(
            project_id=str(uuid4()),
            title=title,
            status="active_in_development",
            current_canon_version="",
            authority_level="creator_supplied_project_context",
            authoritative_source="creator",
            source_reference=record.source_reference.strip()
            or "creator_project_creation_request",
            source_version=record.source_version.strip(),
            approval_status="creator_supplied",
            state_version=1,
            approved_decision_id=None,
            production_constraints=record.production_constraints.strip(),
            initial_creative_intent=initial_creative_intent,
        )

        row = [
            created.project_id,
            created.title,
            created.status,
            created.current_canon_version,
            created.authority_level,
            created.authoritative_source,
            created.source_reference,
            created.source_version,
            created.approval_status,
            created.state_version,
            created.approved_decision_id,
            created.production_constraints,
            created.initial_creative_intent,
        ]
        self._client.insert(
            "projects",
            [row],
            column_names=PROJECT_COLUMNS,
            database=self._config.clickhouse_database,
        )
        return created


class ClickHouseStoryboardPersistence:
    """Application-owned writes for storyboard review and approval state.

    ClickHouse does not provide this code a cross-table transaction spanning
    review_queue, decision_log, and storyboards. This class therefore uses
    deterministic IDs, read-before-write checks, and a final review update as
    the completion marker. If a later write fails after an earlier insert, the
    caller gets a partial-failure exception and can safely retry the same
    request; the retry resumes from the already-written deterministic records.
    """

    def __init__(
        self,
        client: ClickHouseClient | None = None,
        config: StudioOneConfig | None = None,
    ) -> None:
        self._config = config or StudioOneConfig.from_env()
        self._client = client or build_clickhouse_client(self._config)

    def create_storyboard_candidate_review(
        self,
        record: StoryboardCandidateReviewRecord,
    ) -> CreatedStoryboardReviewRecord:
        project_id = _required_uuid(record.project_id, "project_id")
        candidate = _storyboard_candidate_payload(record.storyboard_candidate)
        if candidate.get("project_id") != str(project_id):
            raise ValueError("storyboard candidate project_id must match record project_id")

        serialized_candidate = _json_dumps(candidate)
        now = _utcnow()
        review_id = str(uuid4())
        row = [
            review_id,
            str(project_id),
            None,
            "storyboard_candidate",
            "approve_storyboard",
            "Storyboard candidate requires explicit creator review.",
            "FINALIZE STORYBOARD output is non-authoritative until creator decision.",
            record.source_reference.strip(),
            float(record.confidence),
            "info",
            "pending",
            "",
            "",
            now,
            None,
            "ai_recommendation",
            "gemini" if record.gemini_model.strip() else "",
            record.source_version.strip(),
            list(record.evidence_references),
            "storyboard",
            "creator_approval_required",
            record.gemini_model.strip(),
            record.gemini_response_id.strip(),
            record.gemini_prompt_version.strip(),
            serialized_candidate,
            int(record.recommendation_version),
            str(_required_uuid(record.supersedes_review_id, "supersedes_review_id"))
            if record.supersedes_review_id
            else None,
        ]
        self._client.insert(
            "review_queue",
            [row],
            column_names=REVIEW_QUEUE_COLUMNS,
            database=self._config.clickhouse_database,
        )
        return CreatedStoryboardReviewRecord(
            review_id=review_id,
            project_id=str(project_id),
            status="pending",
            review_type="storyboard_candidate",
            proposed_action="approve_storyboard",
            proposed_state_change=serialized_candidate,
        )

    def decide_storyboard_review(
        self,
        record: CreatorStoryboardDecisionRecord,
    ) -> StoryboardReviewDecisionResult:
        project_id = _required_uuid(record.project_id, "project_id")
        review_id = _required_uuid(record.review_id, "review_id")
        _require_nonempty(record.decided_by, "decided_by")
        _require_nonempty(record.decision_reason, "decision_reason")
        _require_nonempty(
            record.reviewer_identity_source,
            "reviewer_identity_source",
        )
        if record.action not in STORYBOARD_DECISION_VALUES:
            raise ValueError("action must be approve, reject, or needs_revision")

        review = self._get_storyboard_review(str(project_id), str(review_id))
        if not review:
            raise ValueError("storyboard review was not found")
        if review["review_type"] != "storyboard_candidate":
            raise ValueError("review is not a storyboard candidate")
        if review["proposed_action"] != "approve_storyboard":
            raise ValueError("review does not propose storyboard approval")
        if review["authority_level"] != "ai_recommendation":
            raise ValueError("storyboard review must be an AI recommendation")

        decision = STORYBOARD_DECISION_VALUES[record.action]
        decision_id = _deterministic_uuid(
            f"studio_one:storyboard_review_decision:{review_id}:{decision}"
        )
        if review["status"] != "pending":
            if review["status"] != decision:
                raise ValueError("storyboard review is not pending")
            if decision == "approved":
                existing_storyboard = self._storyboard_by_approved_review(
                    str(project_id),
                    str(review_id),
                )
                if not existing_storyboard:
                    raise StoryboardApprovalPartialFailure(
                        "Review is approved but no approved storyboard row was found; "
                        "manual reconciliation is required before a new decision."
                    )
                return StoryboardReviewDecisionResult(
                    project_id=str(project_id),
                    review_id=str(review_id),
                    decision_id=existing_storyboard["approved_decision_id"],
                    decision=decision,
                    review_status=decision,
                    storyboard_id=existing_storyboard["storyboard_id"],
                    storyboard_version=int(existing_storyboard["storyboard_version"]),
                    storyboard_created=False,
                )
            return StoryboardReviewDecisionResult(
                project_id=str(project_id),
                review_id=str(review_id),
                decision_id=decision_id,
                decision=decision,
                review_status=decision,
                storyboard_created=False,
            )

        decided_at = _utcnow()
        previous_storyboard = self._latest_approved_storyboard(str(project_id))
        previous_version = (
            int(previous_storyboard["storyboard_version"])
            if previous_storyboard
            else 0
        )

        if decision == "approved":
            return self._approve_storyboard_review(
                project_id=str(project_id),
                review_id=str(review_id),
                review=review,
                record=record,
                decision_id=decision_id,
                decided_at=decided_at,
                previous_storyboard=previous_storyboard,
                previous_version=previous_version,
            )

        return self._reject_or_request_revision(
            project_id=str(project_id),
            review_id=str(review_id),
            review=review,
            record=record,
            decision=decision,
            decision_id=decision_id,
            decided_at=decided_at,
            previous_version=previous_version,
        )

    def _approve_storyboard_review(
        self,
        project_id: str,
        review_id: str,
        review: dict[str, Any],
        record: CreatorStoryboardDecisionRecord,
        decision_id: str,
        decided_at: datetime,
        previous_storyboard: dict[str, Any] | None,
        previous_version: int,
    ) -> StoryboardReviewDecisionResult:
        existing_storyboard = self._storyboard_by_approved_review(
            project_id,
            review_id,
        )
        if existing_storyboard:
            if review["status"] != "approved":
                self._update_review_status(
                    project_id,
                    review_id,
                    "approved",
                    record.decided_by,
                    record.decision_reason,
                    decided_at,
                )
            return StoryboardReviewDecisionResult(
                project_id=project_id,
                review_id=review_id,
                decision_id=existing_storyboard["approved_decision_id"],
                decision="approved",
                review_status="approved",
                storyboard_id=existing_storyboard["storyboard_id"],
                storyboard_version=int(existing_storyboard["storyboard_version"]),
                storyboard_created=False,
            )

        candidate = _storyboard_candidate_payload(
            json.loads(review["proposed_state_change"])
        )
        new_version = previous_version + 1
        storyboard_id = _deterministic_uuid(
            f"studio_one:approved_storyboard:{review_id}:{new_version}"
        )
        resulting_state = {
            "created_authoritative_storyboard": True,
            "storyboard_id": storyboard_id,
            "storyboard_version": new_version,
            "status": "approved",
            "approval_status": "approved",
        }

        try:
            self._insert_decision_if_missing(
                decision_id=decision_id,
                project_id=project_id,
                review_id=review_id,
                decision="approved",
                record=record,
                review=review,
                decided_at=decided_at,
                previous_state={
                    "review_status": review["status"],
                    "previous_storyboard_version": previous_version,
                },
                resulting_state=resulting_state,
                affected_state_version=previous_version,
                resulting_state_version=new_version,
            )
            self._insert_storyboard_if_missing(
                storyboard_id=storyboard_id,
                project_id=project_id,
                review_id=review_id,
                decision_id=decision_id,
                record=record,
                review=review,
                candidate=candidate,
                storyboard_version=new_version,
                supersedes_storyboard_id=(
                    previous_storyboard["storyboard_id"]
                    if previous_storyboard
                    else None
                ),
                approved_at=decided_at,
            )
            self._update_review_status(
                project_id,
                review_id,
                "approved",
                record.decided_by,
                record.decision_reason,
                decided_at,
            )
        except Exception as exc:
            raise StoryboardApprovalPartialFailure(
                "Storyboard approval uses non-transactional ClickHouse writes. "
                "A partial write may have occurred; retry the same approval "
                "request to resume from deterministic decision/storyboard IDs."
            ) from exc

        return StoryboardReviewDecisionResult(
            project_id=project_id,
            review_id=review_id,
            decision_id=decision_id,
            decision="approved",
            review_status="approved",
            storyboard_id=storyboard_id,
            storyboard_version=new_version,
            storyboard_created=True,
        )

    def _reject_or_request_revision(
        self,
        project_id: str,
        review_id: str,
        review: dict[str, Any],
        record: CreatorStoryboardDecisionRecord,
        decision: str,
        decision_id: str,
        decided_at: datetime,
        previous_version: int,
    ) -> StoryboardReviewDecisionResult:
        try:
            self._insert_decision_if_missing(
                decision_id=decision_id,
                project_id=project_id,
                review_id=review_id,
                decision=decision,
                record=record,
                review=review,
                decided_at=decided_at,
                previous_state={"review_status": review["status"]},
                resulting_state={
                    "created_authoritative_storyboard": False,
                    "review_status": decision,
                },
                affected_state_version=previous_version,
                resulting_state_version=previous_version,
            )
            self._update_review_status(
                project_id,
                review_id,
                decision,
                record.decided_by,
                record.decision_reason,
                decided_at,
            )
        except Exception as exc:
            raise StoryboardApprovalPartialFailure(
                "Storyboard review decision uses non-transactional ClickHouse "
                "writes. A partial decision may have occurred; retry the same "
                "request to finish updating review_queue."
            ) from exc

        return StoryboardReviewDecisionResult(
            project_id=project_id,
            review_id=review_id,
            decision_id=decision_id,
            decision=decision,
            review_status=decision,
            storyboard_created=False,
        )

    def _insert_decision_if_missing(
        self,
        *,
        decision_id: str,
        project_id: str,
        review_id: str,
        decision: str,
        record: CreatorStoryboardDecisionRecord,
        review: dict[str, Any],
        decided_at: datetime,
        previous_state: dict[str, Any],
        resulting_state: dict[str, Any],
        affected_state_version: int,
        resulting_state_version: int,
    ) -> None:
        if self._decision_by_id(project_id, decision_id):
            return

        row = [
            decision_id,
            project_id,
            review_id,
            None,
            decision,
            record.decided_by.strip(),
            record.decision_reason.strip(),
            _json_dumps(previous_state),
            _json_dumps(resulting_state),
            review["proposed_state_change"],
            float(review.get("confidence") or 0.0),
            review.get("source_reference") or "",
            decided_at,
            "human_decision_audit",
            record.reviewer_identity_source.strip(),
            "storyboards",
            int(affected_state_version),
            int(resulting_state_version),
        ]
        self._client.insert(
            "decision_log",
            [row],
            column_names=DECISION_LOG_COLUMNS,
            database=self._config.clickhouse_database,
        )

    def _insert_storyboard_if_missing(
        self,
        *,
        storyboard_id: str,
        project_id: str,
        review_id: str,
        decision_id: str,
        record: CreatorStoryboardDecisionRecord,
        review: dict[str, Any],
        candidate: dict[str, Any],
        storyboard_version: int,
        supersedes_storyboard_id: str | None,
        approved_at: datetime,
    ) -> None:
        if self._storyboard_by_id(project_id, storyboard_id):
            return

        row = [
            storyboard_id,
            project_id,
            int(storyboard_version),
            "approved",
            "approved",
            "approved_production_state",
            candidate.get("working_title", ""),
            candidate.get("target_total_runtime", ""),
            candidate.get("creative_narrative_objective", ""),
            list(candidate.get("production_constraints_applied") or []),
            list(candidate.get("unresolved_issues") or []),
            _json_dumps(candidate),
            STORYBOARD_SCHEMA_VERSION,
            review.get("source_reference") or "",
            review.get("source_version") or "",
            "creator_approval",
            decision_id,
            review_id,
            record.decided_by.strip(),
            record.reviewer_identity_source.strip(),
            approved_at,
            approved_at,
            supersedes_storyboard_id,
        ]
        self._client.insert(
            "storyboards",
            [row],
            column_names=STORYBOARD_COLUMNS,
            database=self._config.clickhouse_database,
        )

    def _get_storyboard_review(
        self,
        project_id: str,
        review_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(review_id) AS review_id,
  toString(project_id) AS project_id,
  review_type,
  proposed_action,
  finding,
  rationale,
  source_reference,
  confidence,
  severity,
  status,
  reviewer,
  reviewer_notes,
  toString(reviewed_at) AS reviewed_at,
  authority_level,
  authoritative_source,
  source_version,
  evidence_references,
  qc_layer,
  qc_type,
  gemini_model,
  gemini_response_id,
  gemini_prompt_version,
  proposed_state_change,
  recommendation_version
FROM `{self._config.clickhouse_database}`.`review_queue`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND review_id = {_uuid_literal(review_id, "review_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _latest_approved_storyboard(self, project_id: str) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  storyboard_version,
  toString(approved_decision_id) AS approved_decision_id,
  toString(approved_review_id) AS approved_review_id
FROM `{self._config.clickhouse_database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
ORDER BY storyboard_version DESC, approved_at DESC, storyboard_id DESC
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _storyboard_by_approved_review(
        self,
        project_id: str,
        review_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  storyboard_version,
  toString(approved_decision_id) AS approved_decision_id,
  toString(approved_review_id) AS approved_review_id
FROM `{self._config.clickhouse_database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND approved_review_id = {_uuid_literal(review_id, "review_id")}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
ORDER BY storyboard_version DESC, approved_at DESC, storyboard_id DESC
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _storyboard_by_id(
        self,
        project_id: str,
        storyboard_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  storyboard_version
FROM `{self._config.clickhouse_database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND storyboard_id = {_uuid_literal(storyboard_id, "storyboard_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _decision_by_id(
        self,
        project_id: str,
        decision_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(decision_id) AS decision_id,
  decision
FROM `{self._config.clickhouse_database}`.`decision_log`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND decision_id = {_uuid_literal(decision_id, "decision_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _update_review_status(
        self,
        project_id: str,
        review_id: str,
        status: str,
        reviewer: str,
        reviewer_notes: str,
        reviewed_at: datetime,
    ) -> None:
        command = f"""
ALTER TABLE `{self._config.clickhouse_database}`.`review_queue`
UPDATE
  status = {_sql_string(status)},
  reviewer = {_sql_string(reviewer.strip())},
  reviewer_notes = {_sql_string(reviewer_notes.strip())},
  reviewed_at = toDateTime({_sql_string(_clickhouse_datetime(reviewed_at))})
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND review_id = {_uuid_literal(review_id, "review_id")}
SETTINGS mutations_sync = 2
""".strip()
        self._client.command(command)


class ClickHouseGenerationPackagePersistence:
    """Application-owned writes for provider-neutral generation instructions."""

    def __init__(
        self,
        client: ClickHouseClient | None = None,
        config: StudioOneConfig | None = None,
    ) -> None:
        self._config = config or StudioOneConfig.from_env()
        self._client = client or build_clickhouse_client(self._config)

    def persist_generate_assets_package(
        self,
        record: GenerationPackageCreateRecord,
    ) -> list[CreatedGenerationPackageRecord]:
        project_id = str(_required_uuid(record.project_id, "project_id"))
        package = _generate_assets_package_payload(record.package)
        if package["project_id"] != project_id:
            raise ValueError("generation package project_id must match record project_id")

        storyboard_id = str(
            _required_uuid(package["approved_storyboard_id"], "approved_storyboard_id")
        )
        storyboard_version = _positive_int(
            package["approved_storyboard_version"],
            "approved_storyboard_version",
        )
        if not self._approved_storyboard_by_id_version(
            project_id,
            storyboard_id,
            storyboard_version,
        ):
            raise ValueError(
                "approved storyboard was not found for generation package provenance"
            )

        created_records: list[CreatedGenerationPackageRecord] = []
        for package_type, package_item in _generation_package_items(package):
            created_records.append(
                self._persist_generation_package_item(
                    project_id=project_id,
                    approved_storyboard_id=storyboard_id,
                    approved_storyboard_version=storyboard_version,
                    package_type=package_type,
                    package_item=package_item,
                    record=record,
                )
            )
        return created_records

    def _persist_generation_package_item(
        self,
        *,
        project_id: str,
        approved_storyboard_id: str,
        approved_storyboard_version: int,
        package_type: str,
        package_item: dict[str, Any],
        record: GenerationPackageCreateRecord,
    ) -> CreatedGenerationPackageRecord:
        storyboard_reference = package_item["storyboard_reference"].strip()
        package_json = _json_dumps(package_item)
        existing_rows = self._generation_packages_for_key(
            project_id=project_id,
            approved_storyboard_id=approved_storyboard_id,
            approved_storyboard_version=approved_storyboard_version,
            storyboard_panel_shot_reference=storyboard_reference,
            package_type=package_type,
        )

        for row in existing_rows:
            if row.get("package_json") == package_json:
                return _created_generation_package_record(row)

        latest = existing_rows[0] if existing_rows else None
        next_version = int(latest["package_version"]) + 1 if latest else 1
        supersedes_id = latest["generation_package_id"] if latest else None
        package_hash = sha256(package_json.encode("utf-8")).hexdigest()
        generation_package_id = _deterministic_uuid(
            "studio_one:generation_package:"
            f"{project_id}:{approved_storyboard_id}:{approved_storyboard_version}:"
            f"{storyboard_reference}:{package_type}:{next_version}:{package_hash}"
        )

        existing_by_id = self._generation_package_by_id_version(
            project_id,
            generation_package_id,
            next_version,
        )
        if existing_by_id:
            return _created_generation_package_record(existing_by_id)

        now = _utcnow()
        row = [
            generation_package_id,
            project_id,
            approved_storyboard_id,
            approved_storyboard_version,
            storyboard_reference,
            package_type,
            next_version,
            GENERATION_PACKAGE_STATUS,
            GENERATION_PACKAGE_AUTHORITY_LEVEL,
            package_json,
            GENERATION_PACKAGE_SCHEMA_VERSION,
            record.source_reference.strip(),
            record.source_version.strip(),
            list(record.evidence_references),
            record.gemini_model.strip(),
            record.gemini_response_id.strip(),
            record.gemini_prompt_version.strip(),
            record.created_by.strip() or "studio_one",
            now,
            supersedes_id,
        ]
        self._client.insert(
            "generation_packages",
            [row],
            column_names=GENERATION_PACKAGE_COLUMNS,
            database=self._config.clickhouse_database,
        )
        return CreatedGenerationPackageRecord(
            generation_package_id=generation_package_id,
            project_id=project_id,
            approved_storyboard_id=approved_storyboard_id,
            approved_storyboard_version=approved_storyboard_version,
            storyboard_panel_shot_reference=storyboard_reference,
            package_type=package_type,
            package_version=next_version,
            status=GENERATION_PACKAGE_STATUS,
            authority_level=GENERATION_PACKAGE_AUTHORITY_LEVEL,
            package_json=package_json,
            supersedes_generation_package_id=supersedes_id,
        )

    def _approved_storyboard_by_id_version(
        self,
        project_id: str,
        storyboard_id: str,
        storyboard_version: int,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  toString(project_id) AS project_id,
  storyboard_version,
  status,
  approval_status,
  authority_level
FROM `{self._config.clickhouse_database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND storyboard_id = {_uuid_literal(storyboard_id, "storyboard_id")}
  AND storyboard_version = {int(storyboard_version)}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _generation_packages_for_key(
        self,
        *,
        project_id: str,
        approved_storyboard_id: str,
        approved_storyboard_version: int,
        storyboard_panel_shot_reference: str,
        package_type: str,
    ) -> list[dict[str, Any]]:
        query = f"""
SELECT
  toString(generation_package_id) AS generation_package_id,
  toString(project_id) AS project_id,
  toString(approved_storyboard_id) AS approved_storyboard_id,
  approved_storyboard_version,
  storyboard_panel_shot_reference,
  package_type,
  package_version,
  status,
  authority_level,
  package_json,
  toString(supersedes_generation_package_id) AS supersedes_generation_package_id
FROM `{self._config.clickhouse_database}`.`generation_packages`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND approved_storyboard_id = {_uuid_literal(approved_storyboard_id, "approved_storyboard_id")}
  AND approved_storyboard_version = {int(approved_storyboard_version)}
  AND storyboard_panel_shot_reference = {_sql_string(storyboard_panel_shot_reference)}
  AND package_type = {_sql_string(package_type)}
ORDER BY package_version DESC, generation_package_id DESC
""".strip()
        return _query_rows(self._client.query(query))

    def _generation_package_by_id_version(
        self,
        project_id: str,
        generation_package_id: str,
        package_version: int,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(generation_package_id) AS generation_package_id,
  toString(project_id) AS project_id,
  toString(approved_storyboard_id) AS approved_storyboard_id,
  approved_storyboard_version,
  storyboard_panel_shot_reference,
  package_type,
  package_version,
  status,
  authority_level,
  package_json,
  toString(supersedes_generation_package_id) AS supersedes_generation_package_id
FROM `{self._config.clickhouse_database}`.`generation_packages`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND generation_package_id = {_uuid_literal(generation_package_id, "generation_package_id")}
  AND package_version = {int(package_version)}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))


class ClickHouseExternalAssetIntakePersistence:
    """Application-owned writes for creator-submitted external asset candidates."""

    def __init__(
        self,
        client: ClickHouseClient | None = None,
        config: StudioOneConfig | None = None,
    ) -> None:
        self._config = config or StudioOneConfig.from_env()
        self._client = client or build_clickhouse_client(self._config)

    def submit_external_asset_candidate(
        self,
        record: ExternalAssetIntakeRecord,
    ) -> CreatedExternalAssetCandidateRecord:
        project_id = str(_required_uuid(record.project_id, "project_id"))
        storyboard_id = str(
            _required_uuid(record.approved_storyboard_id, "approved_storyboard_id")
        )
        storyboard_version = _positive_int(
            record.approved_storyboard_version,
            "approved_storyboard_version",
        )
        storyboard_reference = record.storyboard_panel_shot_reference.strip()
        _require_nonempty(storyboard_reference, "storyboard_panel_shot_reference")
        asset_type = record.asset_type.strip()
        _require_nonempty(asset_type, "asset_type")
        external_asset_reference = record.external_asset_reference.strip()
        _require_nonempty(external_asset_reference, "external_asset_reference")
        submitted_by = record.submitted_by.strip()
        _require_nonempty(submitted_by, "submitted_by")

        if not self._approved_storyboard_by_id_version(
            project_id,
            storyboard_id,
            storyboard_version,
        ):
            raise ValueError("approved storyboard was not found for asset candidate")

        package_id: str | None = None
        package_version = int(record.source_generation_package_version)
        if record.source_generation_package_id:
            package_id = str(
                _required_uuid(
                    record.source_generation_package_id,
                    "source_generation_package_id",
                )
            )
            package_version = _positive_int(
                package_version,
                "source_generation_package_version",
            )
            package = self._generation_package_by_id_version(
                project_id,
                package_id,
                package_version,
            )
            if not package:
                raise ValueError("source generation package was not found")
            if package["approved_storyboard_id"] != storyboard_id:
                raise ValueError("source package storyboard_id does not match intake")
            if int(package["approved_storyboard_version"]) != storyboard_version:
                raise ValueError("source package storyboard_version does not match intake")
            if package["storyboard_panel_shot_reference"] != storyboard_reference:
                raise ValueError("source package storyboard reference does not match intake")
            if package["status"] != GENERATION_PACKAGE_STATUS:
                raise ValueError("source package is not an instruction package")
            if package["authority_level"] != GENERATION_PACKAGE_AUTHORITY_LEVEL:
                raise ValueError("source package authority level is invalid")
        elif package_version:
            raise ValueError(
                "source_generation_package_version requires source_generation_package_id"
            )

        supersedes_id = self._validated_related_candidate_id(
            candidate_id=record.supersedes_external_asset_candidate_id,
            field_name="supersedes_external_asset_candidate_id",
            project_id=project_id,
            storyboard_id=storyboard_id,
            storyboard_version=storyboard_version,
            storyboard_reference=storyboard_reference,
            asset_type=asset_type,
        )
        retry_id = self._validated_related_candidate_id(
            candidate_id=record.retry_of_external_asset_candidate_id,
            field_name="retry_of_external_asset_candidate_id",
            project_id=project_id,
            storyboard_id=storyboard_id,
            storyboard_version=storyboard_version,
            storyboard_reference=storyboard_reference,
            asset_type=asset_type,
        )
        metadata_json = _json_dumps(record.creator_supplied_metadata or {})
        candidate_id = _deterministic_uuid(
            "studio_one:external_asset_candidate:"
            + _json_dumps(
                {
                    "project_id": project_id,
                    "source_generation_package_id": package_id,
                    "source_generation_package_version": package_version,
                    "approved_storyboard_id": storyboard_id,
                    "approved_storyboard_version": storyboard_version,
                    "storyboard_panel_shot_reference": storyboard_reference,
                    "asset_type": asset_type,
                    "external_asset_reference": external_asset_reference,
                    "creator_supplied_metadata_json": metadata_json,
                    "supersedes_external_asset_candidate_id": supersedes_id,
                    "retry_of_external_asset_candidate_id": retry_id,
                }
            )
        )

        existing = self._external_asset_candidate_by_id(project_id, candidate_id)
        if existing:
            return _created_external_asset_candidate_record(existing)

        now = _utcnow()
        row = [
            candidate_id,
            project_id,
            package_id,
            package_version,
            storyboard_id,
            storyboard_version,
            storyboard_reference,
            asset_type,
            external_asset_reference,
            metadata_json,
            EXTERNAL_ASSET_INTAKE_STATUS,
            EXTERNAL_ASSET_QC_STATUS,
            EXTERNAL_ASSET_AUTHORITY_LEVEL,
            record.source_reference.strip(),
            record.source_version.strip(),
            list(record.evidence_references),
            submitted_by,
            now,
            supersedes_id,
            retry_id,
        ]
        self._client.insert(
            "external_asset_intake",
            [row],
            column_names=EXTERNAL_ASSET_INTAKE_COLUMNS,
            database=self._config.clickhouse_database,
        )
        return CreatedExternalAssetCandidateRecord(
            external_asset_candidate_id=candidate_id,
            project_id=project_id,
            source_generation_package_id=package_id,
            source_generation_package_version=package_version,
            approved_storyboard_id=storyboard_id,
            approved_storyboard_version=storyboard_version,
            storyboard_panel_shot_reference=storyboard_reference,
            asset_type=asset_type,
            external_asset_reference=external_asset_reference,
            intake_status=EXTERNAL_ASSET_INTAKE_STATUS,
            qc_status=EXTERNAL_ASSET_QC_STATUS,
            authority_level=EXTERNAL_ASSET_AUTHORITY_LEVEL,
            supersedes_external_asset_candidate_id=supersedes_id,
            retry_of_external_asset_candidate_id=retry_id,
        )

    def _validated_related_candidate_id(
        self,
        *,
        candidate_id: str | None,
        field_name: str,
        project_id: str,
        storyboard_id: str,
        storyboard_version: int,
        storyboard_reference: str,
        asset_type: str,
    ) -> str | None:
        if not candidate_id:
            return None
        parsed = str(_required_uuid(candidate_id, field_name))
        related = self._external_asset_candidate_by_id(project_id, parsed)
        if not related:
            raise ValueError(f"{field_name} was not found")
        if related["approved_storyboard_id"] != storyboard_id:
            raise ValueError(f"{field_name} storyboard_id does not match intake")
        if int(related["approved_storyboard_version"]) != storyboard_version:
            raise ValueError(f"{field_name} storyboard_version does not match intake")
        if related["storyboard_panel_shot_reference"] != storyboard_reference:
            raise ValueError(f"{field_name} storyboard reference does not match intake")
        if related["asset_type"] != asset_type:
            raise ValueError(f"{field_name} asset_type does not match intake")
        return parsed

    def _approved_storyboard_by_id_version(
        self,
        project_id: str,
        storyboard_id: str,
        storyboard_version: int,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  toString(project_id) AS project_id,
  storyboard_version,
  status,
  approval_status,
  authority_level
FROM `{self._config.clickhouse_database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND storyboard_id = {_uuid_literal(storyboard_id, "storyboard_id")}
  AND storyboard_version = {int(storyboard_version)}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _generation_package_by_id_version(
        self,
        project_id: str,
        generation_package_id: str,
        package_version: int,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(generation_package_id) AS generation_package_id,
  toString(project_id) AS project_id,
  toString(approved_storyboard_id) AS approved_storyboard_id,
  approved_storyboard_version,
  storyboard_panel_shot_reference,
  package_type,
  package_version,
  status,
  authority_level,
  package_json
FROM `{self._config.clickhouse_database}`.`generation_packages`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND generation_package_id = {_uuid_literal(generation_package_id, "generation_package_id")}
  AND package_version = {int(package_version)}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _external_asset_candidate_by_id(
        self,
        project_id: str,
        external_asset_candidate_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(external_asset_candidate_id) AS external_asset_candidate_id,
  toString(project_id) AS project_id,
  toString(source_generation_package_id) AS source_generation_package_id,
  source_generation_package_version,
  toString(approved_storyboard_id) AS approved_storyboard_id,
  approved_storyboard_version,
  storyboard_panel_shot_reference,
  asset_type,
  external_asset_reference,
  intake_status,
  qc_status,
  authority_level,
  toString(supersedes_external_asset_candidate_id) AS supersedes_external_asset_candidate_id,
  toString(retry_of_external_asset_candidate_id) AS retry_of_external_asset_candidate_id
FROM `{self._config.clickhouse_database}`.`external_asset_intake`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND external_asset_candidate_id = {_uuid_literal(external_asset_candidate_id, "external_asset_candidate_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))


class ClickHouseQualityControlPersistence:
    """Application-owned writes for QC review, decision, and asset promotion."""

    def __init__(
        self,
        client: ClickHouseClient | None = None,
        config: StudioOneConfig | None = None,
    ) -> None:
        self._config = config or StudioOneConfig.from_env()
        self._client = client or build_clickhouse_client(self._config)

    def create_asset_qc_review(
        self,
        record: QualityControlReviewRecord,
    ) -> CreatedQualityControlReviewRecord:
        project_id = str(_required_uuid(record.project_id, "project_id"))
        candidate_id = str(
            _required_uuid(
                record.external_asset_candidate_id,
                "external_asset_candidate_id",
            )
        )
        assessment = _quality_control_assessment_payload(record.assessment)
        if assessment["project_id"] != project_id:
            raise ValueError("QC assessment project_id must match record project_id")
        if assessment["external_asset_candidate_id"] != candidate_id:
            raise ValueError(
                "QC assessment external_asset_candidate_id must match record"
            )

        serialized_assessment = _json_dumps(assessment)
        assessment_hash = sha256(serialized_assessment.encode("utf-8")).hexdigest()
        review_id = _deterministic_uuid(
            f"studio_one:asset_qc_review:{candidate_id}:{assessment_hash}"
        )
        existing_review = self._asset_qc_review_by_id(project_id, review_id)
        if existing_review:
            candidate = self._external_asset_candidate_by_id(project_id, candidate_id)
            if candidate and candidate["qc_status"] == EXTERNAL_ASSET_QC_STATUS:
                self._update_candidate_qc_status(
                    project_id,
                    candidate_id,
                    QC_REVIEW_PENDING_STATUS,
                )
            return CreatedQualityControlReviewRecord(
                review_id=review_id,
                project_id=project_id,
                external_asset_candidate_id=candidate_id,
                status=existing_review["status"],
                review_type=existing_review["review_type"],
                proposed_action=existing_review["proposed_action"],
                proposed_state_change=existing_review["proposed_state_change"],
                review_created=False,
            )

        candidate = self._validated_candidate_ready_for_qc(project_id, candidate_id)
        self._validate_qc_assessment_provenance(assessment, candidate)

        proposed_action = QC_RECOMMENDATION_ACTIONS[assessment["recommendation"]]
        now = _utcnow()
        row = [
            review_id,
            project_id,
            None,
            QC_REVIEW_TYPE,
            proposed_action,
            "External asset candidate QC recommendation.",
            assessment["rationale"],
            record.source_reference.strip(),
            float(assessment["confidence"]),
            "info",
            "pending",
            "",
            "",
            now,
            None,
            "ai_recommendation",
            "gemini" if record.gemini_model.strip() else "",
            record.source_version.strip(),
            _merged_evidence(
                record.evidence_references,
                assessment.get("evidence_references") or [],
            ),
            "quality_control",
            "external_asset_candidate",
            record.gemini_model.strip(),
            record.gemini_response_id.strip(),
            record.gemini_prompt_version.strip(),
            serialized_assessment,
            int(record.recommendation_version),
            None,
        ]
        try:
            self._client.insert(
                "review_queue",
                [row],
                column_names=REVIEW_QUEUE_COLUMNS,
                database=self._config.clickhouse_database,
            )
            self._update_candidate_qc_status(
                project_id,
                candidate_id,
                QC_REVIEW_PENDING_STATUS,
            )
        except Exception as exc:
            raise QualityControlPartialFailure(
                "QC review creation uses non-transactional ClickHouse writes. "
                "A partial write may have occurred; retry the same assessment "
                "to resume from the deterministic review ID."
            ) from exc

        return CreatedQualityControlReviewRecord(
            review_id=review_id,
            project_id=project_id,
            external_asset_candidate_id=candidate_id,
            status="pending",
            review_type=QC_REVIEW_TYPE,
            proposed_action=proposed_action,
            proposed_state_change=serialized_assessment,
            review_created=True,
        )

    def decide_asset_qc_review(
        self,
        record: CreatorQualityControlDecisionRecord,
    ) -> QualityControlDecisionResult:
        project_id = str(_required_uuid(record.project_id, "project_id"))
        review_id = str(_required_uuid(record.review_id, "review_id"))
        _require_nonempty(record.decided_by, "decided_by")
        _require_nonempty(record.decision_reason, "decision_reason")
        _require_nonempty(
            record.reviewer_identity_source,
            "reviewer_identity_source",
        )
        if record.action not in QC_DECISION_VALUES:
            raise ValueError("action must be approve, reject, or needs_revision")

        review = self._asset_qc_review_by_id(project_id, review_id)
        if not review:
            raise ValueError("QC review was not found")
        if review["review_type"] != QC_REVIEW_TYPE:
            raise ValueError("review is not an asset QC review")
        if review["authority_level"] != "ai_recommendation":
            raise ValueError("QC review must be an AI recommendation")

        assessment = _quality_control_assessment_payload(
            json.loads(review["proposed_state_change"])
        )
        candidate_id = assessment["external_asset_candidate_id"]
        candidate = self._external_asset_candidate_by_id(project_id, candidate_id)
        if not candidate:
            raise ValueError("external asset candidate was not found")

        decision = QC_DECISION_VALUES[record.action]
        decision_id = _deterministic_uuid(
            f"studio_one:asset_qc_decision:{review_id}:{decision}"
        )
        deterministic_asset_id = (
            _deterministic_uuid(f"studio_one:qc_approved_asset:{candidate_id}")
            if decision == "approved"
            else None
        )

        if review["status"] != "pending":
            if review["status"] != decision:
                raise ValueError("QC review is not pending")
            existing_asset = (
                self._asset_by_candidate_id(project_id, candidate_id)
                if decision == "approved"
                else None
            )
            candidate = self._external_asset_candidate_by_id(project_id, candidate_id)
            return QualityControlDecisionResult(
                project_id=project_id,
                review_id=review_id,
                external_asset_candidate_id=candidate_id,
                decision_id=decision_id,
                decision=decision,
                review_status=decision,
                candidate_qc_status=candidate["qc_status"],
                candidate_intake_status=candidate["intake_status"],
                asset_id=(existing_asset or {}).get("asset_id"),
                asset_created=False,
            )

        if decision == "approved":
            return self._approve_asset_qc_review(
                project_id=project_id,
                review_id=review_id,
                review=review,
                candidate=candidate,
                assessment=assessment,
                record=record,
                decision_id=decision_id,
                asset_id=deterministic_asset_id,
            )

        return self._reject_or_request_asset_revision(
            project_id=project_id,
            review_id=review_id,
            review=review,
            candidate=candidate,
            record=record,
            decision=decision,
            decision_id=decision_id,
        )

    def _approve_asset_qc_review(
        self,
        *,
        project_id: str,
        review_id: str,
        review: dict[str, Any],
        candidate: dict[str, Any],
        assessment: dict[str, Any],
        record: CreatorQualityControlDecisionRecord,
        decision_id: str,
        asset_id: str,
    ) -> QualityControlDecisionResult:
        candidate_id = candidate["external_asset_candidate_id"]
        if candidate["qc_status"] not in {
            QC_REVIEW_PENDING_STATUS,
            QC_APPROVED_FOR_PROMOTION_STATUS,
        }:
            raise ValueError("candidate is not waiting for human QC decision")

        decided_at = _utcnow()
        existing_asset = self._asset_by_candidate_id(project_id, candidate_id)
        asset_created = False
        try:
            self._insert_qc_decision_if_missing(
                decision_id=decision_id,
                project_id=project_id,
                review_id=review_id,
                asset_id=asset_id,
                decision="approved",
                record=record,
                review=review,
                candidate=candidate,
                decided_at=decided_at,
                resulting_state={
                    "candidate_qc_status": QC_APPROVED_FOR_PROMOTION_STATUS,
                    "candidate_intake_status": EXTERNAL_ASSET_PROMOTED_STATUS,
                    "asset_id": asset_id,
                    "asset_promoted": True,
                },
                affected_table="assets",
                resulting_state_version=1,
            )
            self._update_candidate_qc_status(
                project_id,
                candidate_id,
                QC_APPROVED_FOR_PROMOTION_STATUS,
            )
            if not existing_asset:
                self._insert_promoted_asset(
                    asset_id=asset_id,
                    project_id=project_id,
                    candidate=candidate,
                    assessment=assessment,
                    decision_id=decision_id,
                    created_at=decided_at,
                )
                asset_created = True
            self._update_qc_review_status(
                project_id,
                review_id,
                "approved",
                record.decided_by,
                record.decision_reason,
                decided_at,
            )
            self._mark_candidate_promoted(project_id, candidate_id)
        except Exception as exc:
            raise QualityControlPartialFailure(
                "QC approval/promotion spans multiple non-transactional "
                "ClickHouse writes. A partial write may have occurred; retry "
                "the same approval request to resume from deterministic IDs."
            ) from exc

        return QualityControlDecisionResult(
            project_id=project_id,
            review_id=review_id,
            external_asset_candidate_id=candidate_id,
            decision_id=decision_id,
            decision="approved",
            review_status="approved",
            candidate_qc_status=QC_APPROVED_FOR_PROMOTION_STATUS,
            candidate_intake_status=EXTERNAL_ASSET_PROMOTED_STATUS,
            asset_id=asset_id,
            asset_created=asset_created,
        )

    def _reject_or_request_asset_revision(
        self,
        *,
        project_id: str,
        review_id: str,
        review: dict[str, Any],
        candidate: dict[str, Any],
        record: CreatorQualityControlDecisionRecord,
        decision: str,
        decision_id: str,
    ) -> QualityControlDecisionResult:
        if candidate["qc_status"] != QC_REVIEW_PENDING_STATUS:
            raise ValueError("candidate is not waiting for human QC decision")

        decided_at = _utcnow()
        try:
            self._insert_qc_decision_if_missing(
                decision_id=decision_id,
                project_id=project_id,
                review_id=review_id,
                asset_id=None,
                decision=decision,
                record=record,
                review=review,
                candidate=candidate,
                decided_at=decided_at,
                resulting_state={
                    "candidate_qc_status": decision,
                    "asset_promoted": False,
                },
                affected_table="external_asset_intake",
                resulting_state_version=0,
            )
            self._update_qc_review_status(
                project_id,
                review_id,
                decision,
                record.decided_by,
                record.decision_reason,
                decided_at,
            )
            self._update_candidate_qc_status(project_id, candidate["external_asset_candidate_id"], decision)
        except Exception as exc:
            raise QualityControlPartialFailure(
                "QC decision uses non-transactional ClickHouse writes. A "
                "partial decision may have occurred; retry the same request "
                "to finish updating review and candidate state."
            ) from exc

        return QualityControlDecisionResult(
            project_id=project_id,
            review_id=review_id,
            external_asset_candidate_id=candidate["external_asset_candidate_id"],
            decision_id=decision_id,
            decision=decision,
            review_status=decision,
            candidate_qc_status=decision,
            candidate_intake_status=candidate["intake_status"],
            asset_id=None,
            asset_created=False,
        )

    def _validated_candidate_ready_for_qc(
        self,
        project_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        candidate = self._external_asset_candidate_by_id(project_id, candidate_id)
        if not candidate:
            raise ValueError("external asset candidate was not found")
        if candidate["project_id"] != project_id:
            raise ValueError("external asset candidate project_id does not match")
        if candidate["intake_status"] != EXTERNAL_ASSET_INTAKE_STATUS:
            raise ValueError("external asset candidate is not submitted for QC")
        if candidate["qc_status"] != EXTERNAL_ASSET_QC_STATUS:
            raise ValueError("external asset candidate is not pending QC")
        if candidate["authority_level"] != EXTERNAL_ASSET_AUTHORITY_LEVEL:
            raise ValueError("external asset candidate authority level is invalid")

        if not self._approved_storyboard_by_id_version(
            project_id,
            candidate["approved_storyboard_id"],
            int(candidate["approved_storyboard_version"]),
        ):
            raise ValueError("candidate approved storyboard provenance is invalid")

        package_id = candidate.get("source_generation_package_id")
        package_version = int(candidate.get("source_generation_package_version") or 0)
        if package_id:
            package = self._generation_package_by_id_version(
                project_id,
                package_id,
                package_version,
            )
            if not package:
                raise ValueError("candidate source generation package is invalid")
            self._validate_candidate_package_match(candidate, package)
        elif package_version:
            raise ValueError("candidate package version requires package ID")
        return candidate

    def _validate_qc_assessment_provenance(
        self,
        assessment: dict[str, Any],
        candidate: dict[str, Any],
    ) -> None:
        if assessment["approved_storyboard_id"] != candidate["approved_storyboard_id"]:
            raise ValueError("QC assessment storyboard_id does not match candidate")
        if int(assessment["approved_storyboard_version"]) != int(
            candidate["approved_storyboard_version"]
        ):
            raise ValueError("QC assessment storyboard_version does not match candidate")
        if assessment["evaluated_asset_type"] != candidate["asset_type"]:
            raise ValueError("QC assessment asset type does not match candidate")

        assessment_package_id = assessment.get("source_generation_package_id")
        candidate_package_id = candidate.get("source_generation_package_id")
        if (assessment_package_id or None) != (candidate_package_id or None):
            raise ValueError("QC assessment generation package ID does not match candidate")
        if int(assessment.get("source_generation_package_version") or 0) != int(
            candidate.get("source_generation_package_version") or 0
        ):
            raise ValueError(
                "QC assessment generation package version does not match candidate"
            )

    def _validate_candidate_package_match(
        self,
        candidate: dict[str, Any],
        package: dict[str, Any],
    ) -> None:
        if package["approved_storyboard_id"] != candidate["approved_storyboard_id"]:
            raise ValueError("candidate package storyboard_id does not match")
        if int(package["approved_storyboard_version"]) != int(
            candidate["approved_storyboard_version"]
        ):
            raise ValueError("candidate package storyboard_version does not match")
        if package["storyboard_panel_shot_reference"] != candidate[
            "storyboard_panel_shot_reference"
        ]:
            raise ValueError("candidate package storyboard reference does not match")
        if package["status"] != GENERATION_PACKAGE_STATUS:
            raise ValueError("candidate package is not an instruction package")
        if package["authority_level"] != GENERATION_PACKAGE_AUTHORITY_LEVEL:
            raise ValueError("candidate package authority level is invalid")

    def _insert_qc_decision_if_missing(
        self,
        *,
        decision_id: str,
        project_id: str,
        review_id: str,
        asset_id: str | None,
        decision: str,
        record: CreatorQualityControlDecisionRecord,
        review: dict[str, Any],
        candidate: dict[str, Any],
        decided_at: datetime,
        resulting_state: dict[str, Any],
        affected_table: str,
        resulting_state_version: int,
    ) -> None:
        if self._decision_by_id(project_id, decision_id):
            return

        row = [
            decision_id,
            project_id,
            review_id,
            asset_id,
            decision,
            record.decided_by.strip(),
            record.decision_reason.strip(),
            _json_dumps(
                {
                    "review_status": review["status"],
                    "candidate_intake_status": candidate["intake_status"],
                    "candidate_qc_status": candidate["qc_status"],
                }
            ),
            _json_dumps(resulting_state),
            review["proposed_state_change"],
            float(review.get("confidence") or 0.0),
            review.get("source_reference") or "",
            decided_at,
            "human_decision_audit",
            record.reviewer_identity_source.strip(),
            affected_table,
            0,
            int(resulting_state_version),
        ]
        self._client.insert(
            "decision_log",
            [row],
            column_names=DECISION_LOG_COLUMNS,
            database=self._config.clickhouse_database,
        )

    def _insert_promoted_asset(
        self,
        *,
        asset_id: str,
        project_id: str,
        candidate: dict[str, Any],
        assessment: dict[str, Any],
        decision_id: str,
        created_at: datetime,
    ) -> None:
        if self._asset_by_candidate_id(project_id, candidate["external_asset_candidate_id"]):
            return

        row = [
            asset_id,
            project_id,
            candidate["asset_type"],
            _asset_name_from_candidate(candidate),
            _asset_description_from_assessment(assessment),
            "approved",
            "",
            f"external_asset_candidate:{candidate['external_asset_candidate_id']}",
            created_at,
            created_at,
            "approved_production_state",
            "creator_qc_approval",
            f"storyboard:{candidate['approved_storyboard_version']}",
            "approved",
            1,
            decision_id,
            None,
            "",
            candidate.get("source_generation_package_id") or None,
            int(candidate.get("source_generation_package_version") or 0),
            candidate["external_asset_candidate_id"],
            candidate["external_asset_reference"],
            candidate.get("creator_supplied_metadata_json") or "",
        ]
        self._client.insert(
            "assets",
            [row],
            column_names=ASSET_COLUMNS,
            database=self._config.clickhouse_database,
        )

    def _asset_qc_review_by_id(
        self,
        project_id: str,
        review_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(review_id) AS review_id,
  toString(project_id) AS project_id,
  toString(asset_id) AS asset_id,
  review_type,
  proposed_action,
  finding,
  rationale,
  source_reference,
  confidence,
  severity,
  status,
  reviewer,
  reviewer_notes,
  toString(reviewed_at) AS reviewed_at,
  authority_level,
  authoritative_source,
  source_version,
  evidence_references,
  qc_layer,
  qc_type,
  gemini_model,
  gemini_response_id,
  gemini_prompt_version,
  proposed_state_change,
  recommendation_version
FROM `{self._config.clickhouse_database}`.`review_queue`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND review_id = {_uuid_literal(review_id, "review_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _approved_storyboard_by_id_version(
        self,
        project_id: str,
        storyboard_id: str,
        storyboard_version: int,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  toString(project_id) AS project_id,
  storyboard_version,
  status,
  approval_status,
  authority_level
FROM `{self._config.clickhouse_database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND storyboard_id = {_uuid_literal(storyboard_id, "storyboard_id")}
  AND storyboard_version = {int(storyboard_version)}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _generation_package_by_id_version(
        self,
        project_id: str,
        generation_package_id: str,
        package_version: int,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(generation_package_id) AS generation_package_id,
  toString(project_id) AS project_id,
  toString(approved_storyboard_id) AS approved_storyboard_id,
  approved_storyboard_version,
  storyboard_panel_shot_reference,
  package_type,
  package_version,
  status,
  authority_level,
  package_json
FROM `{self._config.clickhouse_database}`.`generation_packages`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND generation_package_id = {_uuid_literal(generation_package_id, "generation_package_id")}
  AND package_version = {int(package_version)}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _external_asset_candidate_by_id(
        self,
        project_id: str,
        external_asset_candidate_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(external_asset_candidate_id) AS external_asset_candidate_id,
  toString(project_id) AS project_id,
  toString(source_generation_package_id) AS source_generation_package_id,
  source_generation_package_version,
  toString(approved_storyboard_id) AS approved_storyboard_id,
  approved_storyboard_version,
  storyboard_panel_shot_reference,
  asset_type,
  external_asset_reference,
  creator_supplied_metadata_json,
  intake_status,
  qc_status,
  authority_level,
  source_reference,
  source_version,
  evidence_references,
  submitted_by,
  toString(submitted_at) AS submitted_at,
  toString(supersedes_external_asset_candidate_id) AS supersedes_external_asset_candidate_id,
  toString(retry_of_external_asset_candidate_id) AS retry_of_external_asset_candidate_id
FROM `{self._config.clickhouse_database}`.`external_asset_intake`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND external_asset_candidate_id = {_uuid_literal(external_asset_candidate_id, "external_asset_candidate_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _decision_by_id(
        self,
        project_id: str,
        decision_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(decision_id) AS decision_id,
  decision
FROM `{self._config.clickhouse_database}`.`decision_log`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND decision_id = {_uuid_literal(decision_id, "decision_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _asset_by_candidate_id(
        self,
        project_id: str,
        external_asset_candidate_id: str,
    ) -> dict[str, Any] | None:
        query = f"""
SELECT
  toString(asset_id) AS asset_id,
  toString(project_id) AS project_id,
  toString(external_asset_candidate_id) AS external_asset_candidate_id,
  approval_status,
  authority_level
FROM `{self._config.clickhouse_database}`.`assets`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND external_asset_candidate_id = {_uuid_literal(external_asset_candidate_id, "external_asset_candidate_id")}
LIMIT 1
""".strip()
        return _single_query_row(self._client.query(query))

    def _update_qc_review_status(
        self,
        project_id: str,
        review_id: str,
        status: str,
        reviewer: str,
        reviewer_notes: str,
        reviewed_at: datetime,
    ) -> None:
        command = f"""
ALTER TABLE `{self._config.clickhouse_database}`.`review_queue`
UPDATE
  status = {_sql_string(status)},
  reviewer = {_sql_string(reviewer.strip())},
  reviewer_notes = {_sql_string(reviewer_notes.strip())},
  reviewed_at = toDateTime({_sql_string(_clickhouse_datetime(reviewed_at))})
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND review_id = {_uuid_literal(review_id, "review_id")}
SETTINGS mutations_sync = 2
""".strip()
        self._client.command(command)

    def _update_candidate_qc_status(
        self,
        project_id: str,
        external_asset_candidate_id: str,
        qc_status: str,
    ) -> None:
        command = f"""
ALTER TABLE `{self._config.clickhouse_database}`.`external_asset_intake`
UPDATE
  qc_status = {_sql_string(qc_status)}
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND external_asset_candidate_id = {_uuid_literal(external_asset_candidate_id, "external_asset_candidate_id")}
SETTINGS mutations_sync = 2
""".strip()
        self._client.command(command)

    def _mark_candidate_promoted(
        self,
        project_id: str,
        external_asset_candidate_id: str,
    ) -> None:
        command = f"""
ALTER TABLE `{self._config.clickhouse_database}`.`external_asset_intake`
UPDATE
  intake_status = {_sql_string(EXTERNAL_ASSET_PROMOTED_STATUS)},
  qc_status = {_sql_string(QC_APPROVED_FOR_PROMOTION_STATUS)}
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND external_asset_candidate_id = {_uuid_literal(external_asset_candidate_id, "external_asset_candidate_id")}
SETTINGS mutations_sync = 2
""".strip()
        self._client.command(command)


def _quality_control_assessment_payload(assessment: dict[str, Any]) -> dict[str, Any]:
    payload = assessment.get("structured_output", assessment)
    if not isinstance(payload, dict):
        raise ValueError("quality control assessment must be a dict")

    required_fields = {
        "project_id",
        "external_asset_candidate_id",
        "approved_storyboard_id",
        "approved_storyboard_version",
        "source_generation_package_id",
        "source_generation_package_version",
        "evaluated_asset_type",
        "storyboard_alignment",
        "prompt_instruction_alignment",
        "continuity_assessment",
        "production_constraint_assessment",
        "technical_quality_assessment",
        "dialogue_audio_assessment",
        "provenance_assessment",
        "detected_issues",
        "required_corrections",
        "strengths",
        "recommendation",
        "confidence",
        "rationale",
        "evidence_references",
        "governance_boundary",
    }
    missing = sorted(field for field in required_fields if field not in payload)
    if missing:
        raise ValueError(f"quality control assessment missing fields: {', '.join(missing)}")

    prohibited_fields = {
        "approved",
        "approved_for_promotion",
        "qc_approved_asset",
        "human_approved",
        "promoted_to_assets",
    }
    present = sorted(field for field in prohibited_fields if field in payload)
    if present:
        raise ValueError(
            "quality control assessment cannot contain approval fields: "
            + ", ".join(present)
        )
    if payload["recommendation"] not in QC_RECOMMENDATION_ACTIONS:
        raise ValueError("QC recommendation is invalid")

    payload = dict(payload)
    payload["project_id"] = str(_required_uuid(payload["project_id"], "project_id"))
    payload["external_asset_candidate_id"] = str(
        _required_uuid(
            payload["external_asset_candidate_id"],
            "external_asset_candidate_id",
        )
    )
    payload["approved_storyboard_id"] = str(
        _required_uuid(payload["approved_storyboard_id"], "approved_storyboard_id")
    )
    payload["approved_storyboard_version"] = _positive_int(
        payload["approved_storyboard_version"],
        "approved_storyboard_version",
    )
    if payload.get("source_generation_package_id"):
        payload["source_generation_package_id"] = str(
            _required_uuid(
                payload["source_generation_package_id"],
                "source_generation_package_id",
            )
        )
        payload["source_generation_package_version"] = _positive_int(
            payload["source_generation_package_version"],
            "source_generation_package_version",
        )
    else:
        payload["source_generation_package_id"] = None
        payload["source_generation_package_version"] = 0

    for field_name in (
        "detected_issues",
        "required_corrections",
        "strengths",
        "evidence_references",
    ):
        if not isinstance(payload[field_name], list):
            raise ValueError(f"{field_name} must be a list")

    return payload


def _merged_evidence(
    first: tuple[str, ...],
    second: list[Any],
) -> list[str]:
    merged: list[str] = []
    for item in [*first, *second]:
        value = str(item).strip()
        if value and value not in merged:
            merged.append(value)
    return merged


def _asset_name_from_candidate(candidate: dict[str, Any]) -> str:
    metadata = _json_loads_dict(candidate.get("creator_supplied_metadata_json") or "")
    for key in ("name", "title", "filename"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return (
        f"{candidate['asset_type']} for "
        f"{candidate['storyboard_panel_shot_reference']}"
    )


def _asset_description_from_assessment(assessment: dict[str, Any]) -> str:
    for key in (
        "storyboard_alignment",
        "prompt_instruction_alignment",
        "provenance_assessment",
    ):
        value = assessment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Creator-approved external asset promoted after QC."


def _json_loads_dict(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _generate_assets_package_payload(package: dict[str, Any]) -> dict[str, Any]:
    payload = package.get("structured_output", package)
    if not isinstance(payload, dict):
        raise ValueError("generation package must be a dict")

    required_fields = {
        "stage",
        "project_id",
        "approved_storyboard_id",
        "approved_storyboard_version",
        "package_status",
        "image_prompt_packages",
        "video_prompt_packages",
        "dialogue_audio_handoffs",
        "sound_music_handoffs",
    }
    missing = sorted(field for field in required_fields if field not in payload)
    if missing:
        raise ValueError(f"generation package missing fields: {', '.join(missing)}")
    if payload["stage"] != "generate_assets":
        raise ValueError("generation package stage must be generate_assets")
    if payload["package_status"] != GENERATION_PACKAGE_STATUS:
        raise ValueError("generation package status must be instructions_for_creator")

    prohibited_fields = {
        "generated_assets",
        "externally_generated_asset",
        "qc_approved_assets",
        "approved_for_promotion",
    }
    present = sorted(field for field in prohibited_fields if field in payload)
    if present:
        raise ValueError(
            "generation package cannot contain asset or approval fields: "
            + ", ".join(present)
        )
    return payload


def _generation_package_items(
    package: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    project_id = str(_required_uuid(package["project_id"], "project_id"))
    storyboard_id = str(
        _required_uuid(package["approved_storyboard_id"], "approved_storyboard_id")
    )
    storyboard_version = _positive_int(
        package["approved_storyboard_version"],
        "approved_storyboard_version",
    )

    collections = [
        ("image_prompt_packages", "image_prompt"),
        ("video_prompt_packages", "video_prompt"),
        ("dialogue_audio_handoffs", "dialogue_audio_handoff"),
        ("sound_music_handoffs", "sound_music_handoff"),
    ]

    items: list[tuple[str, dict[str, Any]]] = []
    for collection_name, package_type in collections:
        raw_items = package.get(collection_name) or []
        if not isinstance(raw_items, list):
            raise ValueError(f"{collection_name} must be a list")
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError(f"{collection_name} entries must be dicts")
            item = dict(raw_item)
            if item.get("project_id") and item["project_id"] != project_id:
                raise ValueError("package item project_id does not match package")
            if item.get("approved_storyboard_id") and item[
                "approved_storyboard_id"
            ] != storyboard_id:
                raise ValueError("package item storyboard_id does not match package")
            if item.get("approved_storyboard_version") and int(
                item["approved_storyboard_version"]
            ) != storyboard_version:
                raise ValueError(
                    "package item storyboard_version does not match package"
                )
            if any(
                field in item
                for field in (
                    "generated_asset",
                    "generated_assets",
                    "qc_approved_asset",
                    "qc_approved_assets",
                    "approved_for_promotion",
                )
            ):
                raise ValueError("package item cannot claim asset generation or approval")

            storyboard_reference = item.get("storyboard_reference", "")
            _require_nonempty(storyboard_reference, "storyboard_reference")
            item["project_id"] = project_id
            item["approved_storyboard_id"] = storyboard_id
            item["approved_storyboard_version"] = storyboard_version
            item["package_type"] = package_type
            item["package_status"] = GENERATION_PACKAGE_STATUS
            item["authority_level"] = GENERATION_PACKAGE_AUTHORITY_LEVEL
            item["asset_state_boundary"] = package.get("asset_state_boundary", "")
            item["provider_selection_boundary"] = package.get(
                "provider_selection_boundary",
                "",
            )
            item["governance_boundary"] = package.get("governance_boundary", "")
            item["package_provenance_references"] = list(
                package.get("provenance_references") or []
            )
            item["generation_prompt_is_asset"] = False
            items.append((package_type, item))

    return items


def _created_generation_package_record(
    row: dict[str, Any],
) -> CreatedGenerationPackageRecord:
    return CreatedGenerationPackageRecord(
        generation_package_id=row["generation_package_id"],
        project_id=row["project_id"],
        approved_storyboard_id=row["approved_storyboard_id"],
        approved_storyboard_version=int(row["approved_storyboard_version"]),
        storyboard_panel_shot_reference=row["storyboard_panel_shot_reference"],
        package_type=row["package_type"],
        package_version=int(row["package_version"]),
        status=row["status"],
        authority_level=row["authority_level"],
        package_json=row["package_json"],
        supersedes_generation_package_id=(
            row.get("supersedes_generation_package_id") or None
        ),
    )


def _created_external_asset_candidate_record(
    row: dict[str, Any],
) -> CreatedExternalAssetCandidateRecord:
    return CreatedExternalAssetCandidateRecord(
        external_asset_candidate_id=row["external_asset_candidate_id"],
        project_id=row["project_id"],
        source_generation_package_id=row.get("source_generation_package_id") or None,
        source_generation_package_version=int(
            row.get("source_generation_package_version") or 0
        ),
        approved_storyboard_id=row["approved_storyboard_id"],
        approved_storyboard_version=int(row["approved_storyboard_version"]),
        storyboard_panel_shot_reference=row["storyboard_panel_shot_reference"],
        asset_type=row["asset_type"],
        external_asset_reference=row["external_asset_reference"],
        intake_status=row["intake_status"],
        qc_status=row["qc_status"],
        authority_level=row["authority_level"],
        supersedes_external_asset_candidate_id=(
            row.get("supersedes_external_asset_candidate_id") or None
        ),
        retry_of_external_asset_candidate_id=(
            row.get("retry_of_external_asset_candidate_id") or None
        ),
    )


def _required_uuid(value: str | None, field_name: str) -> UUID:
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _uuid_literal(value: str, field_name: str) -> str:
    return f"toUUID('{_required_uuid(value, field_name)}')"


def _require_nonempty(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")


def _storyboard_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = candidate.get("structured_output", candidate)
    if not isinstance(payload, dict):
        raise ValueError("storyboard candidate must be a dict")

    required_fields = {
        "project_id",
        "working_title",
        "target_total_runtime",
        "creative_narrative_objective",
        "production_constraints_applied",
        "unresolved_issues",
        "approval_governance_status",
        "panels",
    }
    missing = sorted(field for field in required_fields if field not in payload)
    if missing:
        raise ValueError(f"storyboard candidate missing fields: {', '.join(missing)}")
    if not payload.get("panels"):
        raise ValueError("storyboard candidate must contain at least one panel")

    return payload


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _deterministic_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, value))


def _single_query_row(result: Any) -> dict[str, Any] | None:
    rows = getattr(result, "result_rows", []) or []
    if not rows:
        return None
    names = getattr(result, "column_names", None)
    if names is None:
        names = getattr(result, "columns", None)
    if names is None:
        raise RuntimeError("ClickHouse query result did not expose column names")
    return dict(zip(names, rows[0]))


def _query_rows(result: Any) -> list[dict[str, Any]]:
    rows = getattr(result, "result_rows", []) or []
    names = getattr(result, "column_names", None)
    if names is None:
        names = getattr(result, "columns", None)
    if names is None:
        raise RuntimeError("ClickHouse query result did not expose column names")
    return [dict(zip(names, row)) for row in rows]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _clickhouse_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
