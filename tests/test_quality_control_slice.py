from __future__ import annotations

import inspect
import json
import re
import unittest
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import patch

from pydantic import ValidationError

from studio_one.agents import refinement_agent
from studio_one.agents.refinement_agent import (
    NON_FABRICATION_STATEMENT,
    QUALITY_CONTROL_GOVERNANCE_BOUNDARY,
    QualityControlAssessment,
    QualityControlContextRequiredError,
)
from studio_one.integrations import clickhouse_mcp
from studio_one.integrations.clickhouse_mcp import _approved_storyboard_query
from studio_one.integrations.clickhouse_mcp import _external_asset_candidate_query
from studio_one.integrations.clickhouse_mcp import _generation_package_query
from studio_one.integrations.clickhouse_persistence import (
    ASSET_COLUMNS,
    DECISION_LOG_COLUMNS,
    EXTERNAL_ASSET_INTAKE_COLUMNS,
    GENERATION_PACKAGE_COLUMNS,
    REVIEW_QUEUE_COLUMNS,
    ClickHouseQualityControlPersistence,
    CreatorQualityControlDecisionRecord,
    QualityControlPartialFailure,
    QualityControlReviewRecord,
)
from studio_one.services.quality_control_service import QualityControlDecisionRequest
from studio_one.services.quality_control_service import QualityControlRequest
from studio_one.services.quality_control_service import QualityControlService
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS
from studio_one.workflow.stages import IMPLEMENTED_STAGE_IDENTIFIERS
from studio_one.workflow.stages import StudioOneStage

from test_project_creation_slice import TEST_CONFIG


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_PROJECT_ID = "22222222-2222-4222-8222-222222222222"
STORYBOARD_ID = "33333333-3333-4333-8333-333333333333"
PACKAGE_ID = "44444444-4444-4444-8444-444444444444"
CANDIDATE_ID = "55555555-5555-4555-8555-555555555555"


class FakeQueryResult:
    def __init__(self, column_names: list[str], rows: list[list[Any]]) -> None:
        self.column_names = column_names
        self.result_rows = rows


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "storyboards": [
                {
                    "storyboard_id": STORYBOARD_ID,
                    "project_id": PROJECT_ID,
                    "storyboard_version": 1,
                    "status": "approved",
                    "approval_status": "approved",
                    "authority_level": "approved_production_state",
                }
            ],
            "generation_packages": [
                _generation_package_row(
                    generation_package_id=PACKAGE_ID,
                    project_id=PROJECT_ID,
                    approved_storyboard_id=STORYBOARD_ID,
                    approved_storyboard_version=1,
                    storyboard_panel_shot_reference="panel 1",
                )
            ],
            "external_asset_intake": [
                _candidate_row(
                    external_asset_candidate_id=CANDIDATE_ID,
                    project_id=PROJECT_ID,
                    source_generation_package_id=PACKAGE_ID,
                    source_generation_package_version=1,
                    approved_storyboard_id=STORYBOARD_ID,
                    approved_storyboard_version=1,
                    storyboard_panel_shot_reference="panel 1",
                )
            ],
            "review_queue": [],
            "decision_log": [],
            "assets": [],
        }
        self.commands: list[str] = []
        self.fail_next_candidate_update = False

    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str],
        database: str | None = None,
    ) -> None:
        for row in data:
            self.tables.setdefault(table, []).append(dict(zip(column_names, row)))

    def query(self, query: str) -> FakeQueryResult:
        if ".`storyboards`" in query:
            project_id, storyboard_id = _uuids(query)[:2]
            storyboard_version = _number_assignment(query, "storyboard_version")
            rows = [
                row
                for row in self.tables["storyboards"]
                if row["project_id"] == project_id
                and row["storyboard_id"] == storyboard_id
                and row["storyboard_version"] == storyboard_version
                and row["status"] == "approved"
                and row["approval_status"] == "approved"
                and row["authority_level"] == "approved_production_state"
            ]
            return _result(
                [
                    "storyboard_id",
                    "project_id",
                    "storyboard_version",
                    "status",
                    "approval_status",
                    "authority_level",
                ],
                rows,
            )

        if ".`generation_packages`" in query:
            project_id, package_id = _uuids(query)[:2]
            package_version = _number_assignment(query, "package_version")
            rows = [
                row
                for row in self.tables["generation_packages"]
                if row["project_id"] == project_id
                and row["generation_package_id"] == package_id
                and row["package_version"] == package_version
            ]
            return _result(
                [
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
                ],
                rows,
            )

        if ".`external_asset_intake`" in query:
            project_id, candidate_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["external_asset_intake"]
                if row["project_id"] == project_id
                and row["external_asset_candidate_id"] == candidate_id
            ]
            return _result(_external_candidate_columns(), rows)

        if ".`review_queue`" in query:
            project_id, review_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["review_queue"]
                if row["project_id"] == project_id and row["review_id"] == review_id
            ]
            return _result(_review_columns(), rows)

        if ".`decision_log`" in query:
            project_id, decision_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["decision_log"]
                if row["project_id"] == project_id
                and row["decision_id"] == decision_id
            ]
            return _result(["decision_id", "decision"], rows)

        if ".`assets`" in query:
            project_id, candidate_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["assets"]
                if row["project_id"] == project_id
                and row["external_asset_candidate_id"] == candidate_id
            ]
            return _result(
                [
                    "asset_id",
                    "project_id",
                    "external_asset_candidate_id",
                    "approval_status",
                    "authority_level",
                ],
                rows,
            )

        raise AssertionError(f"Unexpected query: {query}")

    def command(self, command: str) -> None:
        self.commands.append(command)
        if ".`external_asset_intake`" in command:
            if self.fail_next_candidate_update:
                self.fail_next_candidate_update = False
                raise RuntimeError("simulated candidate update failure")
            project_id, candidate_id = _uuids(command)[:2]
            for row in self.tables["external_asset_intake"]:
                if (
                    row["project_id"] == project_id
                    and row["external_asset_candidate_id"] == candidate_id
                ):
                    if _has_assignment(command, "intake_status"):
                        row["intake_status"] = _assignment(command, "intake_status")
                    if _has_assignment(command, "qc_status"):
                        row["qc_status"] = _assignment(command, "qc_status")
                    return

        if ".`review_queue`" in command:
            project_id, review_id = _uuids(command)[:2]
            for row in self.tables["review_queue"]:
                if row["project_id"] == project_id and row["review_id"] == review_id:
                    row["status"] = _assignment(command, "status")
                    row["reviewer"] = _assignment(command, "reviewer")
                    row["reviewer_notes"] = _assignment(command, "reviewer_notes")
                    row["reviewed_at"] = "updated"
                    return

        raise AssertionError(f"Unexpected command: {command}")


def _result(columns: list[str], rows: list[dict[str, Any]]) -> FakeQueryResult:
    return FakeQueryResult(
        columns,
        [[row.get(column) for column in columns] for row in rows],
    )


def _uuids(text: str) -> list[str]:
    return re.findall(r"toUUID\('([^']+)'\)", text)


def _number_assignment(text: str, field: str) -> int:
    match = re.search(rf"{field}\s*=\s*(\d+)", text)
    if not match:
        raise AssertionError(f"Missing number assignment for {field}: {text}")
    return int(match.group(1))


def _assignment(text: str, field: str) -> str:
    match = re.search(rf"{field}\s*=\s*'((?:\\'|[^'])*)'", text)
    if not match:
        raise AssertionError(f"Missing assignment for {field}: {text}")
    return match.group(1).replace("\\'", "'").replace("\\\\", "\\")


def _has_assignment(text: str, field: str) -> bool:
    return re.search(rf"{field}\s*=", text) is not None


def _generation_package_row(
    *,
    generation_package_id: str,
    project_id: str,
    approved_storyboard_id: str,
    approved_storyboard_version: int,
    storyboard_panel_shot_reference: str,
) -> dict[str, Any]:
    row = dict.fromkeys(GENERATION_PACKAGE_COLUMNS)
    row.update(
        {
            "generation_package_id": generation_package_id,
            "project_id": project_id,
            "approved_storyboard_id": approved_storyboard_id,
            "approved_storyboard_version": approved_storyboard_version,
            "storyboard_panel_shot_reference": storyboard_panel_shot_reference,
            "package_type": "image_prompt",
            "package_version": 1,
            "status": "instructions_for_creator",
            "authority_level": "production_instruction",
            "package_json": "{}",
            "package_schema_version": "generation_package:v1",
        }
    )
    return row


def _candidate_row(
    *,
    external_asset_candidate_id: str,
    project_id: str,
    source_generation_package_id: str | None,
    source_generation_package_version: int,
    approved_storyboard_id: str,
    approved_storyboard_version: int,
    storyboard_panel_shot_reference: str,
    qc_status: str = "pending_qc",
) -> dict[str, Any]:
    row = dict.fromkeys(EXTERNAL_ASSET_INTAKE_COLUMNS)
    row.update(
        {
            "external_asset_candidate_id": external_asset_candidate_id,
            "project_id": project_id,
            "source_generation_package_id": source_generation_package_id,
            "source_generation_package_version": source_generation_package_version,
            "approved_storyboard_id": approved_storyboard_id,
            "approved_storyboard_version": approved_storyboard_version,
            "storyboard_panel_shot_reference": storyboard_panel_shot_reference,
            "asset_type": "image",
            "external_asset_reference": "creator-submitted://asset-001",
            "creator_supplied_metadata_json": json.dumps(
                {"filename": "creator-file.png"}
            ),
            "intake_status": "submitted_for_qc",
            "qc_status": qc_status,
            "authority_level": "external_asset_candidate",
            "source_reference": "creator_external_upload",
            "source_version": "",
            "evidence_references": [],
            "submitted_by": "creator@example.com",
            "submitted_at": "2026-08-27 00:00:00",
            "supersedes_external_asset_candidate_id": None,
            "retry_of_external_asset_candidate_id": None,
        }
    )
    return row


def _external_candidate_columns() -> list[str]:
    return [
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


def _review_columns() -> list[str]:
    return [
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
    ]


def _qc_memory(
    *,
    candidate: dict[str, Any] | None = None,
    storyboard: dict[str, Any] | None = None,
    package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = candidate if candidate is not None else _candidate_row(
        external_asset_candidate_id=CANDIDATE_ID,
        project_id=PROJECT_ID,
        source_generation_package_id=PACKAGE_ID,
        source_generation_package_version=1,
        approved_storyboard_id=STORYBOARD_ID,
        approved_storyboard_version=1,
        storyboard_panel_shot_reference="panel 1",
    )
    storyboard = storyboard if storyboard is not None else {
        "storyboard_id": STORYBOARD_ID,
        "project_id": PROJECT_ID,
        "storyboard_version": 1,
        "status": "approved",
        "approval_status": "approved",
        "authority_level": "approved_production_state",
        "storyboard_json": json.dumps(
            {
                "panels": [
                    {
                        "panel_shot_number": 1,
                        "story_purpose": "Evaluate creator media.",
                    }
                ]
            }
        ),
    }
    package = package if package is not None else {
        "generation_package_id": PACKAGE_ID,
        "project_id": PROJECT_ID,
        "approved_storyboard_id": STORYBOARD_ID,
        "approved_storyboard_version": 1,
        "storyboard_panel_shot_reference": "panel 1",
        "package_version": 1,
        "status": "instructions_for_creator",
        "authority_level": "production_instruction",
        "package_json": "{}",
    }
    return {
        "project": {
            "project_id": PROJECT_ID,
            "title": "Creator Project",
            "production_constraints": "Creator production constraints.",
            "initial_creative_intent": "Creator durable intent.",
        },
        "approved_storyboard": storyboard,
        "relevant_storyboard_panel": {"panel_shot_number": 1},
        "generation_package": package,
        "external_asset_candidate": candidate,
        "assets": [],
        "assets_count": 0,
    }


def _qc_report(
    *,
    memory: dict[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    production_memory = memory or _qc_memory()
    return {
        "stage": "quality_control",
        "runtime": {
            "gemini_model_used": "gemini-2.5-flash",
            "mcp_retrieval_evidence": {"mcp_tool_invoked": "run_query"},
            "clickhouse_writes_performed": False,
        },
        "validation": {"agent_memory_retrieval_path": "official_mcp_clickhouse"},
        "production_memory": production_memory,
        "structured_output": assessment or _qc_assessment(),
    }


def _qc_assessment(
    *,
    recommendation: str = "recommend_approve",
    source_generation_package_id: str | None = PACKAGE_ID,
    source_generation_package_version: int = 1,
) -> dict[str, Any]:
    return {
        "stage": "quality_control",
        "project_id": PROJECT_ID,
        "external_asset_candidate_id": CANDIDATE_ID,
        "approved_storyboard_id": STORYBOARD_ID,
        "approved_storyboard_version": 1,
        "source_generation_package_id": source_generation_package_id,
        "source_generation_package_version": source_generation_package_version,
        "evaluated_asset_type": "image",
        "storyboard_alignment": "Matches the panel intent.",
        "prompt_instruction_alignment": "Matches the instruction package.",
        "continuity_assessment": "No continuity conflict detected.",
        "production_constraint_assessment": "Fits creator constraints.",
        "technical_quality_assessment": "Usable for the intended edit.",
        "dialogue_audio_assessment": "Not applicable to this visual candidate.",
        "provenance_assessment": "Traceable to candidate and package.",
        "detected_issues": [],
        "required_corrections": [],
        "strengths": ["Clear visual alignment."],
        "recommendation": recommendation,
        "confidence": 0.87,
        "rationale": "The candidate matches the available production context.",
        "evidence_references": [
            "storyboard:1:panel:1",
            f"external_asset_candidate:{CANDIDATE_ID}",
        ],
        "governance_boundary": QUALITY_CONTROL_GOVERNANCE_BOUNDARY,
        "non_fabrication_statement": NON_FABRICATION_STATEMENT,
    }


def _review_record(
    recommendation: str = "recommend_approve",
) -> QualityControlReviewRecord:
    return QualityControlReviewRecord(
        project_id=PROJECT_ID,
        external_asset_candidate_id=CANDIDATE_ID,
        assessment=_qc_assessment(recommendation=recommendation),
        gemini_model="gemini-2.5-flash",
        evidence_references=("mcp:qc-memory",),
    )


def _persistence(client: FakeClickHouseClient) -> ClickHouseQualityControlPersistence:
    return ClickHouseQualityControlPersistence(client=client, config=TEST_CONFIG)


def _create_review(
    client: FakeClickHouseClient,
    recommendation: str = "recommend_approve",
) -> str:
    review = _persistence(client).create_asset_qc_review(
        _review_record(recommendation=recommendation)
    )
    return review.review_id


def _decision_record(
    review_id: str,
    action: str,
    *,
    decided_by: str = "creator@example.com",
    decision_reason: str = "Explicit creator QC decision.",
) -> CreatorQualityControlDecisionRecord:
    return CreatorQualityControlDecisionRecord(
        project_id=PROJECT_ID,
        review_id=review_id,
        action=action,  # type: ignore[arg-type]
        decided_by=decided_by,
        decision_reason=decision_reason,
        reviewer_identity_source="manual",
    )


class QualityControlAgentGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_external_candidate_fails_closed(self) -> None:
        memory = _qc_memory(candidate=None)
        memory["external_asset_candidate"] = None

        with patch.object(
            refinement_agent,
            "retrieve_qc_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(),
        ) as run_agent:
            with self.assertRaises(QualityControlContextRequiredError):
                await refinement_agent.run_quality_control_agent(PROJECT_ID, CANDIDATE_ID)

        run_agent.assert_not_called()

    async def test_wrong_project_fails_closed(self) -> None:
        candidate = _candidate_row(
            external_asset_candidate_id=CANDIDATE_ID,
            project_id=OTHER_PROJECT_ID,
            source_generation_package_id=PACKAGE_ID,
            source_generation_package_version=1,
            approved_storyboard_id=STORYBOARD_ID,
            approved_storyboard_version=1,
            storyboard_panel_shot_reference="panel 1",
        )
        memory = _qc_memory(candidate=candidate)

        with patch.object(
            refinement_agent,
            "retrieve_qc_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(refinement_agent, "_run_stage_agent", new=AsyncMock()):
            with self.assertRaises(QualityControlContextRequiredError):
                await refinement_agent.run_quality_control_agent(PROJECT_ID, CANDIDATE_ID)

    async def test_invalid_storyboard_provenance_fails_closed(self) -> None:
        memory = _qc_memory(storyboard=None)
        memory["approved_storyboard"] = None

        with patch.object(
            refinement_agent,
            "retrieve_qc_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(refinement_agent, "_run_stage_agent", new=AsyncMock()):
            with self.assertRaises(QualityControlContextRequiredError):
                await refinement_agent.run_quality_control_agent(PROJECT_ID, CANDIDATE_ID)

    async def test_invalid_generation_package_provenance_fails_closed(self) -> None:
        memory = _qc_memory(package=None)
        memory["generation_package"] = None

        with patch.object(
            refinement_agent,
            "retrieve_qc_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(refinement_agent, "_run_stage_agent", new=AsyncMock()):
            with self.assertRaises(QualityControlContextRequiredError):
                await refinement_agent.run_quality_control_agent(PROJECT_ID, CANDIDATE_ID)

    async def test_valid_creator_existing_media_without_package_can_be_qcd(self) -> None:
        candidate = _candidate_row(
            external_asset_candidate_id=CANDIDATE_ID,
            project_id=PROJECT_ID,
            source_generation_package_id=None,
            source_generation_package_version=0,
            approved_storyboard_id=STORYBOARD_ID,
            approved_storyboard_version=1,
            storyboard_panel_shot_reference="panel 1",
        )
        memory = _qc_memory(candidate=candidate, package=None)
        memory["generation_package"] = None
        assessment = _qc_assessment(
            source_generation_package_id=None,
            source_generation_package_version=0,
        )

        with patch.object(
            refinement_agent,
            "retrieve_qc_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(return_value=_qc_report(memory=memory, assessment=assessment)),
        ) as run_agent:
            report = await refinement_agent.run_quality_control_agent(
                PROJECT_ID,
                CANDIDATE_ID,
            )

        self.assertEqual(report["structured_output"]["recommendation"], "recommend_approve")
        self.assertEqual(report["validation"]["agent_memory_retrieval_path"], "official_mcp_clickhouse")
        self.assertEqual(run_agent.call_args.kwargs["stage"], StudioOneStage.QUALITY_CONTROL)

    def test_qc_reasoning_uses_mcp_not_direct_clickhouse(self) -> None:
        source = inspect.getsource(refinement_agent)

        self.assertIn("retrieve_qc_memory_bundle", source)
        self.assertNotIn("clickhouse_connect", source)
        self.assertNotIn("ClickHouseQualityControlPersistence", source)

    def test_gemini_cannot_output_promotion_fields(self) -> None:
        payload = _qc_assessment()
        payload["approved_for_promotion"] = True

        with self.assertRaises(ValidationError):
            QualityControlAssessment.model_validate(payload)


class QualityControlPersistenceTests(unittest.TestCase):
    def test_gemini_recommendation_creates_pending_human_review_only(self) -> None:
        client = FakeClickHouseClient()

        review = _persistence(client).create_asset_qc_review(_review_record())

        self.assertEqual(review.status, "pending")
        self.assertEqual(review.review_type, "asset_qc")
        self.assertEqual(review.proposed_action, "approve_asset")
        self.assertEqual(len(client.tables["review_queue"]), 1)
        self.assertEqual(client.tables["review_queue"][0]["authority_level"], "ai_recommendation")
        self.assertEqual(client.tables["review_queue"][0]["status"], "pending")
        self.assertEqual(client.tables["external_asset_intake"][0]["qc_status"], "qc_review_pending_human_decision")
        self.assertEqual(client.tables["assets"], [])
        self.assertEqual(client.tables["decision_log"], [])

    def test_gemini_recommendation_cannot_directly_approve_or_promote(self) -> None:
        client = FakeClickHouseClient()
        assessment = _qc_assessment()
        assessment["promoted_to_assets"] = True

        with self.assertRaises(ValueError):
            _persistence(client).create_asset_qc_review(
                QualityControlReviewRecord(
                    project_id=PROJECT_ID,
                    external_asset_candidate_id=CANDIDATE_ID,
                    assessment=assessment,
                )
            )

        self.assertEqual(client.tables["review_queue"], [])
        self.assertEqual(client.tables["assets"], [])

    def test_approve_requires_explicit_human_identity_and_rationale(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client)

        with self.assertRaises(ValueError):
            _persistence(client).decide_asset_qc_review(
                _decision_record(review_id, "approve", decided_by=" ")
            )

        with self.assertRaises(ValueError):
            _persistence(client).decide_asset_qc_review(
                _decision_record(review_id, "approve", decision_reason=" ")
            )

    def test_reject_creates_decision_and_zero_assets(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client, recommendation="recommend_reject")

        result = _persistence(client).decide_asset_qc_review(
            _decision_record(review_id, "reject")
        )

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(len(client.tables["decision_log"]), 1)
        self.assertEqual(client.tables["decision_log"][0]["decision"], "rejected")
        self.assertEqual(client.tables["review_queue"][0]["status"], "rejected")
        self.assertEqual(client.tables["external_asset_intake"][0]["qc_status"], "rejected")
        self.assertEqual(client.tables["assets"], [])

    def test_needs_revision_creates_decision_and_zero_assets(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client, recommendation="recommend_revision")

        result = _persistence(client).decide_asset_qc_review(
            _decision_record(review_id, "needs_revision")
        )

        self.assertEqual(result.decision, "needs_revision")
        self.assertEqual(len(client.tables["decision_log"]), 1)
        self.assertEqual(client.tables["review_queue"][0]["status"], "needs_revision")
        self.assertEqual(client.tables["external_asset_intake"][0]["qc_status"], "needs_revision")
        self.assertEqual(client.tables["assets"], [])

    def test_approve_creates_exactly_one_authoritative_asset(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client)

        result = _persistence(client).decide_asset_qc_review(
            _decision_record(review_id, "approve")
        )

        self.assertEqual(result.decision, "approved")
        self.assertTrue(result.asset_created)
        self.assertEqual(len(client.tables["decision_log"]), 1)
        self.assertEqual(len(client.tables["assets"]), 1)
        asset = client.tables["assets"][0]
        self.assertEqual(set(asset), set(ASSET_COLUMNS))
        self.assertEqual(asset["authority_level"], "approved_production_state")
        self.assertEqual(asset["approval_status"], "approved")
        self.assertEqual(asset["authoritative_source"], "creator_qc_approval")
        self.assertEqual(asset["external_asset_candidate_id"], CANDIDATE_ID)
        self.assertEqual(asset["source_generation_package_id"], PACKAGE_ID)
        self.assertEqual(asset["source_generation_package_version"], 1)
        self.assertEqual(asset["external_asset_reference"], "creator-submitted://asset-001")
        self.assertEqual(asset["external_asset_metadata_json"], json.dumps({"filename": "creator-file.png"}))

    def test_successful_promotion_sets_intake_status_promoted_to_assets(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client)

        _persistence(client).decide_asset_qc_review(_decision_record(review_id, "approve"))

        candidate = client.tables["external_asset_intake"][0]
        self.assertEqual(candidate["intake_status"], "promoted_to_assets")
        self.assertEqual(candidate["qc_status"], "approved_for_promotion")

    def test_retrying_same_approval_is_idempotent(self) -> None:
        client = FakeClickHouseClient()
        persistence = _persistence(client)
        review_id = _create_review(client)

        first = persistence.decide_asset_qc_review(_decision_record(review_id, "approve"))
        second = persistence.decide_asset_qc_review(_decision_record(review_id, "approve"))

        self.assertTrue(first.asset_created)
        self.assertFalse(second.asset_created)
        self.assertEqual(len(client.tables["decision_log"]), 1)
        self.assertEqual(len(client.tables["assets"]), 1)
        self.assertEqual(first.asset_id, second.asset_id)

    def test_partial_failure_is_surfaced(self) -> None:
        client = FakeClickHouseClient()
        client.fail_next_candidate_update = True

        with self.assertRaises(QualityControlPartialFailure):
            _persistence(client).create_asset_qc_review(_review_record())

        self.assertEqual(len(client.tables["review_queue"]), 1)
        self.assertEqual(client.tables["external_asset_intake"][0]["qc_status"], "pending_qc")

    def test_rejected_candidate_remains_historically_available(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client, recommendation="recommend_reject")

        _persistence(client).decide_asset_qc_review(_decision_record(review_id, "reject"))

        self.assertEqual(len(client.tables["external_asset_intake"]), 1)
        self.assertEqual(client.tables["external_asset_intake"][0]["qc_status"], "rejected")
        self.assertEqual(client.tables["assets"], [])

    def test_review_rows_use_expected_columns(self) -> None:
        client = FakeClickHouseClient()

        _create_review(client)

        self.assertEqual(set(client.tables["review_queue"][0]), set(REVIEW_QUEUE_COLUMNS))

    def test_decision_rows_use_expected_columns(self) -> None:
        client = FakeClickHouseClient()
        review_id = _create_review(client)

        _persistence(client).decide_asset_qc_review(_decision_record(review_id, "reject"))

        self.assertEqual(set(client.tables["decision_log"][0]), set(DECISION_LOG_COLUMNS))


class QualityControlServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_persists_pending_review_after_agent_assessment(self) -> None:
        client = FakeClickHouseClient()

        async def fake_runner(**_: object) -> dict[str, Any]:
            return _qc_report()

        service = QualityControlService(
            writer=_persistence(client),
            quality_control_runner=fake_runner,
        )

        result = await service.run_quality_control(
            QualityControlRequest(
                project_id=PROJECT_ID,
                external_asset_candidate_id=CANDIDATE_ID,
            )
        )

        self.assertEqual(result.stage, "quality_control")
        self.assertEqual(result.review["status"], "pending")
        self.assertEqual(len(client.tables["review_queue"]), 1)
        self.assertEqual(client.tables["assets"], [])

    def test_service_human_decision_promotes_only_on_approval(self) -> None:
        client = FakeClickHouseClient()
        service = QualityControlService(writer=_persistence(client))
        review_id = _create_review(client)

        result = service.decide_quality_control_review(
            QualityControlDecisionRequest(
                project_id=PROJECT_ID,
                review_id=review_id,
                action="approve",
                decided_by="creator@example.com",
                decision_reason="Explicit creator approval.",
                reviewer_identity_source="manual",
            )
        )

        self.assertEqual(result["decision"], "approved")
        self.assertEqual(len(client.tables["assets"]), 1)


class QualityControlMcpTests(unittest.TestCase):
    def test_qc_mcp_queries_are_exact_and_read_only(self) -> None:
        storyboard_query = _approved_storyboard_query(PROJECT_ID, STORYBOARD_ID, 1, "test_db")
        package_query = _generation_package_query(PROJECT_ID, PACKAGE_ID, 1, "test_db")
        candidate_query = _external_asset_candidate_query(PROJECT_ID, CANDIDATE_ID, "test_db")

        self.assertIn("storyboard_id =", storyboard_query)
        self.assertIn("storyboard_version = 1", storyboard_query)
        self.assertIn("status = 'approved'", storyboard_query)
        self.assertIn("generation_package_id =", package_query)
        self.assertIn("package_version = 1", package_query)
        self.assertIn("external_asset_candidate_id =", candidate_query)
        self.assertIn("qc_status = 'pending_qc'", candidate_query)

    def test_qc_bundle_uses_official_mcp_path(self) -> None:
        source = inspect.getsource(clickhouse_mcp)

        self.assertIn("retrieve_qc_memory_bundle", source)
        self.assertIn("mcp_clickhouse.main", source)
        self.assertIn('"CLICKHOUSE_ALLOW_WRITE_ACCESS": "false"', source)
        self.assertIn("_approved_storyboard_query", source)
        self.assertIn("_generation_package_query", source)
        self.assertIn("_external_asset_candidate_query", source)

    def test_no_non_google_ai_runtime_provider_is_introduced(self) -> None:
        runtime_source = "\n".join(
            [
                inspect.getsource(refinement_agent),
                inspect.getsource(clickhouse_mcp),
            ]
        )

        self.assertNotIn("requests.", runtime_source)
        self.assertNotIn("httpx.", runtime_source)
        self.assertNotIn("imagegen", runtime_source)
        self.assertNotIn("tts_provider", runtime_source)

    def test_exactly_seven_canonical_stages_remain(self) -> None:
        self.assertEqual(
            CANONICAL_STAGE_IDENTIFIERS,
            (
                "brainstorm",
                "refine",
                "finalize_storyboard",
                "generate_assets",
                "quality_control",
                "post_production",
                "publish",
            ),
        )
        self.assertEqual(
            IMPLEMENTED_STAGE_IDENTIFIERS,
            (
                "brainstorm",
                "refine",
                "finalize_storyboard",
                "generate_assets",
                "quality_control",
                "post_production",
                "publish",
            ),
        )


if __name__ == "__main__":
    unittest.main()
