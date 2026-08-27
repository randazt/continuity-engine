from __future__ import annotations

import inspect
import json
import re
import unittest
from dataclasses import asdict
from typing import Any

from studio_one.agents import refinement_agent
from studio_one.integrations import clickhouse_mcp
from studio_one.integrations.clickhouse_mcp import _latest_approved_storyboard_query
from studio_one.integrations.clickhouse_persistence import (
    DECISION_LOG_COLUMNS,
    REVIEW_QUEUE_COLUMNS,
    STORYBOARD_COLUMNS,
    ClickHouseStoryboardPersistence,
    CreatedStoryboardReviewRecord,
    StoryboardReviewDecisionResult,
)
from studio_one.services.storyboard_service import DecideStoryboardReviewRequest
from studio_one.services.storyboard_service import StoryboardService
from studio_one.services.storyboard_service import SubmitStoryboardCandidateReviewRequest
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS

from test_project_creation_slice import TEST_CONFIG


PROJECT_ID = "11111111-1111-4111-8111-111111111111"


class FakeQueryResult:
    def __init__(self, column_names: list[str], rows: list[list[Any]]) -> None:
        self.column_names = column_names
        self.result_rows = rows


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "review_queue": [],
            "decision_log": [],
            "storyboards": [],
            "assets": [],
        }
        self.commands: list[str] = []

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
        if ".`review_queue`" in query:
            project_id, review_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["review_queue"]
                if row["project_id"] == project_id and row["review_id"] == review_id
            ]
            columns = [
                "review_id",
                "project_id",
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
            return _result(columns, rows)

        if ".`decision_log`" in query:
            project_id, decision_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["decision_log"]
                if row["project_id"] == project_id
                and row["decision_id"] == decision_id
            ]
            return _result(["decision_id", "decision"], rows)

        if ".`storyboards`" in query:
            uuid_values = _uuids(query)
            project_id = uuid_values[0]
            rows = [
                row for row in self.tables["storyboards"] if row["project_id"] == project_id
            ]
            if "approved_review_id =" in query:
                review_id = uuid_values[1]
                rows = [row for row in rows if row["approved_review_id"] == review_id]
            elif "storyboard_id =" in query:
                storyboard_id = uuid_values[1]
                rows = [row for row in rows if row["storyboard_id"] == storyboard_id]
            else:
                rows = [
                    row
                    for row in rows
                    if row["status"] == "approved"
                    and row["approval_status"] == "approved"
                    and row["authority_level"] == "approved_production_state"
                ]
            rows = sorted(
                rows,
                key=lambda row: (row["storyboard_version"], row.get("approved_at"), row["storyboard_id"]),
                reverse=True,
            )
            columns = [
                "storyboard_id",
                "storyboard_version",
                "approved_decision_id",
                "approved_review_id",
            ]
            return _result(columns, rows[:1])

        raise AssertionError(f"Unexpected query: {query}")

    def command(self, command: str) -> None:
        self.commands.append(command)
        project_id, review_id = _uuids(command)[:2]
        status = _assignment(command, "status")
        reviewer = _assignment(command, "reviewer")
        reviewer_notes = _assignment(command, "reviewer_notes")
        for row in self.tables["review_queue"]:
            if row["project_id"] == project_id and row["review_id"] == review_id:
                row["status"] = status
                row["reviewer"] = reviewer
                row["reviewer_notes"] = reviewer_notes
                row["reviewed_at"] = "updated"


def _result(columns: list[str], rows: list[dict[str, Any]]) -> FakeQueryResult:
    return FakeQueryResult(columns, [[row.get(column) for column in columns] for row in rows])


def _uuids(text: str) -> list[str]:
    return re.findall(r"toUUID\('([^']+)'\)", text)


def _assignment(command: str, field: str) -> str:
    match = re.search(rf"{field}\s*=\s*'((?:\\'|[^'])*)'", command)
    if not match:
        raise AssertionError(f"Missing assignment for {field}: {command}")
    return match.group(1).replace("\\'", "'")


def storyboard_candidate(project_id: str = PROJECT_ID, title: str = "Creator Project") -> dict[str, Any]:
    return {
        "stage": "finalize_storyboard",
        "project_id": project_id,
        "working_title": title,
        "target_total_runtime": "60 seconds",
        "creative_narrative_objective": "Clarify the production objective.",
        "production_constraints_applied": ["Use creator-approved visual constraints."],
        "unresolved_issues": ["Creator must approve the candidate."],
        "approval_governance_status": "Storyboard candidate for creator approval.",
        "panels": [
            {
                "panel_shot_number": 1,
                "duration": "0:00-0:05",
                "story_purpose": "Establish the premise.",
                "visual_description": "Opening image.",
                "visual_treatment": "Naturalistic.",
                "composition": "Centered subject.",
                "camera_framing": "Wide frame.",
                "lighting": "Soft key light.",
                "environment": "Creator-defined setting.",
                "image_generation_prompt": "Prompt instructions, not an asset.",
                "video_generation_prompt": "Motion prompt instructions.",
                "dialogue": "",
                "voice_tts_direction": "Measured voice direction.",
                "sound_effects": ["Room tone"],
                "ambience": "Quiet interior ambience.",
                "music_direction": "Sparse music bed.",
                "editing_notes": "Cut on action.",
                "continuity_notes": "Maintain established palette.",
                "asset_requirements": ["Primary background"],
                "reuse_opportunities": ["Reuse approved background if available."],
                "production_notes": "Keep unresolved facts out of prompts.",
            }
        ],
        "non_fabrication_statement": "Do not invent missing production facts.",
    }


def service_with_fake_client() -> tuple[StoryboardService, FakeClickHouseClient]:
    client = FakeClickHouseClient()
    persistence = ClickHouseStoryboardPersistence(client=client, config=TEST_CONFIG)
    return StoryboardService(persistence=persistence), client


def submit_review(
    service: StoryboardService,
    candidate: dict[str, Any] | None = None,
) -> CreatedStoryboardReviewRecord:
    return service.submit_candidate_for_review(
        SubmitStoryboardCandidateReviewRequest(
            project_id=PROJECT_ID,
            storyboard_candidate=candidate or storyboard_candidate(),
            source_reference="finalize_storyboard_agent",
            source_version="",
            gemini_model="gemini-2.5-flash",
            gemini_prompt_version="finalize_storyboard:v1",
            evidence_references=["mcp:project-memory"],
            confidence=0.0,
        )
    )


def decide(
    service: StoryboardService,
    review_id: str,
    action: str = "approve",
) -> StoryboardReviewDecisionResult:
    return service.decide_review(
        DecideStoryboardReviewRequest(
            project_id=PROJECT_ID,
            review_id=review_id,
            action=action,
            decided_by="creator@example.com",
            decision_reason="Explicit creator decision.",
            reviewer_identity_source="manual",
        )
    )


class StoryboardApprovalSliceTests(unittest.TestCase):
    def test_storyboard_candidate_can_become_pending_review(self) -> None:
        service, client = service_with_fake_client()

        review = submit_review(service)

        self.assertEqual(review.status, "pending")
        self.assertEqual(len(client.tables["review_queue"]), 1)
        row = client.tables["review_queue"][0]
        self.assertEqual(set(row), set(REVIEW_QUEUE_COLUMNS))
        self.assertEqual(row["review_type"], "storyboard_candidate")
        self.assertEqual(row["proposed_action"], "approve_storyboard")
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["authority_level"], "ai_recommendation")
        self.assertEqual(
            json.loads(row["proposed_state_change"])["project_id"],
            PROJECT_ID,
        )

    def test_candidate_alone_creates_no_approved_storyboard(self) -> None:
        service, client = service_with_fake_client()

        submit_review(service)

        self.assertEqual(client.tables["storyboards"], [])
        self.assertEqual(client.tables["decision_log"], [])
        self.assertEqual(client.tables["assets"], [])

    def test_approval_requires_explicit_creator_identity_and_rationale(self) -> None:
        service, _client = service_with_fake_client()
        review = submit_review(service)

        with self.assertRaises(ValueError):
            service.decide_review(
                DecideStoryboardReviewRequest(
                    project_id=PROJECT_ID,
                    review_id=review.review_id,
                    action="approve",
                    decided_by=" ",
                    decision_reason="Explicit creator decision.",
                    reviewer_identity_source="manual",
                )
            )

        with self.assertRaises(ValueError):
            service.decide_review(
                DecideStoryboardReviewRequest(
                    project_id=PROJECT_ID,
                    review_id=review.review_id,
                    action="approve",
                    decided_by="creator@example.com",
                    decision_reason=" ",
                    reviewer_identity_source="manual",
                )
            )

    def test_approval_creates_correct_human_decision_semantics(self) -> None:
        service, client = service_with_fake_client()
        review = submit_review(service)

        result = decide(service, review.review_id)

        self.assertEqual(result.decision, "approved")
        self.assertEqual(len(client.tables["decision_log"]), 1)
        row = client.tables["decision_log"][0]
        self.assertEqual(set(row), set(DECISION_LOG_COLUMNS))
        self.assertEqual(row["decision"], "approved")
        self.assertEqual(row["decided_by"], "creator@example.com")
        self.assertEqual(row["authority_level"], "human_decision_audit")
        self.assertEqual(row["reviewer_identity_source"], "manual")
        self.assertEqual(row["affected_table"], "storyboards")
        self.assertEqual(row["affected_state_version"], 0)
        self.assertEqual(row["resulting_state_version"], 1)
        self.assertTrue(json.loads(row["resulting_state"])["created_authoritative_storyboard"])

    def test_approval_creates_immutable_storyboard_version(self) -> None:
        service, client = service_with_fake_client()
        review = submit_review(service)

        result = decide(service, review.review_id)

        self.assertEqual(result.storyboard_version, 1)
        self.assertEqual(len(client.tables["storyboards"]), 1)
        row = client.tables["storyboards"][0]
        self.assertEqual(set(row), set(STORYBOARD_COLUMNS))
        self.assertEqual(row["storyboard_version"], 1)
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["approval_status"], "approved")
        self.assertEqual(row["authority_level"], "approved_production_state")
        self.assertEqual(row["authoritative_source"], "creator_approval")
        self.assertEqual(row["approved_review_id"], review.review_id)
        self.assertEqual(row["approved_decision_id"], result.decision_id)
        self.assertIsNone(row["supersedes_storyboard_id"])
        self.assertEqual(json.loads(row["storyboard_json"])["project_id"], PROJECT_ID)

    def test_subsequent_approved_revision_gets_next_version_and_supersedes_prior(self) -> None:
        service, client = service_with_fake_client()
        first_review = submit_review(service)
        first = decide(service, first_review.review_id)
        second_review = submit_review(
            service,
            storyboard_candidate(title="Creator Project Revised"),
        )

        second = decide(service, second_review.review_id)

        self.assertEqual(first.storyboard_version, 1)
        self.assertEqual(second.storyboard_version, 2)
        self.assertEqual(len(client.tables["storyboards"]), 2)
        second_row = client.tables["storyboards"][1]
        self.assertEqual(second_row["storyboard_version"], 2)
        self.assertEqual(second_row["supersedes_storyboard_id"], first.storyboard_id)

    def test_reject_creates_decision_and_no_storyboard(self) -> None:
        service, client = service_with_fake_client()
        review = submit_review(service)

        result = decide(service, review.review_id, action="reject")

        self.assertEqual(result.decision, "rejected")
        self.assertEqual(len(client.tables["decision_log"]), 1)
        self.assertEqual(client.tables["decision_log"][0]["decision"], "rejected")
        self.assertEqual(client.tables["review_queue"][0]["status"], "rejected")
        self.assertEqual(client.tables["storyboards"], [])

    def test_needs_revision_creates_decision_and_no_storyboard(self) -> None:
        service, client = service_with_fake_client()
        review = submit_review(service)

        result = decide(service, review.review_id, action="needs_revision")

        self.assertEqual(result.decision, "needs_revision")
        self.assertEqual(len(client.tables["decision_log"]), 1)
        self.assertEqual(client.tables["decision_log"][0]["decision"], "needs_revision")
        self.assertEqual(client.tables["review_queue"][0]["status"], "needs_revision")
        self.assertEqual(client.tables["storyboards"], [])

    def test_no_assets_are_created_by_any_storyboard_review_decision(self) -> None:
        service, client = service_with_fake_client()
        approve_review = submit_review(service)
        reject_review = submit_review(service)
        revision_review = submit_review(service)

        decide(service, approve_review.review_id, action="approve")
        decide(service, reject_review.review_id, action="reject")
        decide(service, revision_review.review_id, action="needs_revision")

        self.assertEqual(client.tables["assets"], [])

    def test_no_fake_approval_or_canon_state_is_created_for_pending_review(self) -> None:
        service, client = service_with_fake_client()

        submit_review(service)

        row = client.tables["review_queue"][0]
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["authority_level"], "ai_recommendation")
        self.assertNotEqual(row["authority_level"], "approved_production_state")
        self.assertEqual(client.tables["decision_log"], [])
        self.assertEqual(client.tables["storyboards"], [])


class StoryboardMcpRetrievalTests(unittest.TestCase):
    def test_latest_approved_storyboard_query_uses_authoritative_storyboard_state(self) -> None:
        query = _latest_approved_storyboard_query(PROJECT_ID, "test_db")

        self.assertIn("FROM `test_db`.`storyboards`", query)
        self.assertIn("status = 'approved'", query)
        self.assertIn("approval_status = 'approved'", query)
        self.assertIn("authority_level = 'approved_production_state'", query)
        self.assertIn(
            "ORDER BY storyboard_version DESC, approved_at DESC, storyboard_id DESC",
            query,
        )
        self.assertIn("LIMIT 1", query)
        self.assertNotIn("review_queue", query)

    def test_mcp_bundle_retrieves_latest_approved_storyboard_through_mcp(self) -> None:
        source = inspect.getsource(clickhouse_mcp)

        self.assertIn("_latest_approved_storyboard_query", source)
        self.assertIn("latest_approved_storyboard", source)
        self.assertIn("await _run_query", source)
        self.assertIn("CLICKHOUSE_ALLOW_WRITE_ACCESS", source)
        self.assertIn('"false"', source)

    def test_storyboard_candidate_alone_is_insufficient_for_mcp_authority(self) -> None:
        query = _latest_approved_storyboard_query(PROJECT_ID, "test_db")

        self.assertIn("storyboards", query)
        self.assertNotIn("proposed_state_change", query)
        self.assertNotIn("storyboard_candidate", query)

    def test_agent_reasoning_does_not_directly_query_clickhouse(self) -> None:
        source = inspect.getsource(refinement_agent)

        self.assertIn("retrieve_project_memory_bundle", source)
        self.assertNotIn("clickhouse_connect", source)
        self.assertNotIn("ClickHouseStoryboardPersistence", source)

    def test_exactly_seven_canonical_workflow_stage_identifiers_remain(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
