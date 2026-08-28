from __future__ import annotations

import inspect
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import patch

from pydantic import ValidationError

from studio_one.agents import refinement_agent
from studio_one.agents.refinement_agent import (
    NON_FABRICATION_STATEMENT,
    POST_PRODUCTION_GOVERNANCE_BOUNDARY,
    PostProductionContextRequiredError,
    PostProductionPackage,
)
from studio_one.integrations import clickhouse_mcp
from studio_one.integrations.clickhouse_mcp import _approved_assets_for_storyboard_query
from studio_one.integrations.clickhouse_mcp import _unresolved_qc_issues_query
from studio_one.services.post_production_service import PostProductionRequest
from studio_one.services.post_production_service import PostProductionService
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS
from studio_one.workflow.stages import IMPLEMENTED_STAGE_IDENTIFIERS
from studio_one.workflow.stages import StudioOneStage


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
STORYBOARD_ID = "22222222-2222-4222-8222-222222222222"
ASSET_ID = "33333333-3333-4333-8333-333333333333"
SECOND_ASSET_ID = "44444444-4444-4444-8444-444444444444"
PACKAGE_ID = "55555555-5555-4555-8555-555555555555"
CANDIDATE_ID = "66666666-6666-4666-8666-666666666666"


def _storyboard_json() -> str:
    return json.dumps(
        {
            "panels": [
                {
                    "panel_shot_number": 1,
                    "duration": "5 seconds",
                    "story_purpose": "Establish the opening idea.",
                    "visual_treatment": "Clean cinematic realism.",
                    "composition": "Wide establishing frame.",
                    "camera_framing": "Wide shot.",
                    "video_generation_prompt": "Subtle motion.",
                    "dialogue": "Opening line.",
                    "voice_tts_direction": "Grounded delivery.",
                    "sound_effects": ["Soft room tone"],
                    "ambience": "Quiet interior.",
                    "music_direction": "Sparse pulse.",
                    "editing_notes": "Hold before cutting.",
                    "continuity_notes": "Keep lighting consistent.",
                    "asset_requirements": ["approved opening plate"],
                },
                {
                    "panel_shot_number": 2,
                    "duration": "4 seconds",
                    "story_purpose": "Pay off the setup.",
                    "visual_treatment": "Sharper contrast.",
                    "composition": "Medium frame.",
                    "camera_framing": "Medium shot.",
                    "video_generation_prompt": "Slow push.",
                    "dialogue": "",
                    "voice_tts_direction": "",
                    "sound_effects": ["Small impact"],
                    "ambience": "Low exterior bed.",
                    "music_direction": "Resolve the cue.",
                    "editing_notes": "Cut on movement.",
                    "continuity_notes": "Match wardrobe and color.",
                    "asset_requirements": ["approved payoff plate"],
                },
            ]
        }
    )


def _approved_asset(
    asset_id: str = ASSET_ID,
    storyboard_reference: str = "panel 1",
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "project_id": PROJECT_ID,
        "asset_type": "image",
        "name": f"Approved asset {storyboard_reference}",
        "description": "Creator-approved production asset.",
        "approval_status": "approved",
        "authority_level": "approved_production_state",
        "external_asset_reference": f"creator-submitted://{asset_id}",
        "source_reference": f"external_asset_candidate:{CANDIDATE_ID}",
        "source_generation_package_id": PACKAGE_ID,
        "source_generation_package_version": 1,
        "external_asset_candidate_id": CANDIDATE_ID,
        "storyboard_panel_shot_reference": storyboard_reference,
    }


def _post_production_memory(
    *,
    storyboard: dict[str, Any] | None = None,
    assets: list[dict[str, Any]] | None = None,
    unresolved_qc: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    latest_storyboard = storyboard
    if latest_storyboard is None:
        latest_storyboard = {
            "storyboard_id": STORYBOARD_ID,
            "project_id": PROJECT_ID,
            "storyboard_version": 1,
            "status": "approved",
            "approval_status": "approved",
            "authority_level": "approved_production_state",
            "title": "Creator Project",
            "target_total_runtime": "9 seconds",
            "creative_narrative_objective": "Communicate the core idea clearly.",
            "production_constraints_applied": "Keep visuals restrained.",
            "unresolved_issues": [],
            "storyboard_json": _storyboard_json(),
        }
    return {
        "project": {
            "project_id": PROJECT_ID,
            "title": "Creator Project",
            "production_constraints": "Keep visuals restrained.",
        },
        "latest_approved_storyboard": latest_storyboard,
        "storyboard_panels": json.loads(latest_storyboard["storyboard_json"]).get(
            "panels",
            [],
        )
        if latest_storyboard
        else [],
        "approved_assets": assets
        if assets is not None
        else [
            _approved_asset(ASSET_ID, "panel 1"),
            _approved_asset(SECOND_ASSET_ID, "panel 2"),
        ],
        "unresolved_qc_issues": unresolved_qc or [],
        "decision_log_entries": [],
        "assets_count": len(assets or []),
    }


def _readiness(
    *,
    status: str = "ready_for_editing_package",
    missing: list[str] | None = None,
    unresolved: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "approved_storyboard_present": True,
        "required_storyboard_shots_panels": ["panel 1", "panel 2"],
        "approved_asset_coverage_per_shot": [
            {
                "storyboard_reference": "panel 1",
                "required_asset": "approved opening plate",
                "coverage_status": "covered"
                if status == "ready_for_editing_package"
                else "missing",
                "approved_asset_references": []
                if missing
                else [ASSET_ID],
                "notes": "Mapped to approved production asset.",
            }
        ],
        "missing_required_assets": missing or [],
        "unresolved_qc_issues": unresolved or [],
        "dialogue_availability": ["panel 1 dialogue available"],
        "sound_effects_requirements": ["Soft room tone", "Small impact"],
        "ambience_requirements": ["Quiet interior", "Low exterior bed"],
        "music_requirements": ["Sparse pulse", "Resolve the cue"],
        "continuity_concerns": ["Confirm color continuity during edit."],
        "unresolved_production_issues": [],
        "readiness_status": status,
        "return_to_stage": "generate_assets"
        if status == "not_ready_missing_assets"
        else "quality_control"
        if status == "not_ready_unresolved_qc"
        else "",
    }


def _edit_item(
    panel_number: int,
    asset_id: str,
    *,
    dialogue: str = "Opening line.",
) -> dict[str, Any]:
    return {
        "panel_shot_number": panel_number,
        "approved_asset_references": [asset_id],
        "intended_duration": "5 seconds" if panel_number == 1 else "4 seconds",
        "storyboard_purpose": "Establish the opening idea."
        if panel_number == 1
        else "Pay off the setup.",
        "visual_treatment": "Clean cinematic realism.",
        "framing_composition_reference": "Use the approved storyboard composition.",
        "video_motion_intent": "Follow the approved storyboard motion.",
        "dialogue": dialogue,
        "voice_performance_direction": "Grounded delivery.",
        "sound_effects": ["Soft room tone"] if panel_number == 1 else ["Small impact"],
        "ambience": "Quiet interior." if panel_number == 1 else "Low exterior bed.",
        "music_cue": "Sparse pulse." if panel_number == 1 else "Resolve the cue.",
        "transition_into_shot": "Start from black." if panel_number == 1 else "Cut on movement.",
        "transition_out_of_shot": "Straight cut.",
        "editorial_movement_camera_notes": "Keep movement aligned with storyboard.",
        "pacing_hold_notes": "Hold long enough for the story beat to land.",
        "continuity_notes": "Keep lighting and color consistent.",
        "approved_asset_provenance": [asset_id],
    }


def _valid_post_production_output(
    *,
    readiness_status: str = "ready_for_editing_package",
    missing: list[str] | None = None,
    unresolved: list[str] | None = None,
    asset_reference: str = ASSET_ID,
) -> dict[str, Any]:
    return {
        "stage": "post_production",
        "project_id": PROJECT_ID,
        "approved_storyboard_id": STORYBOARD_ID,
        "approved_storyboard_version": 1,
        "package_status": "instructions_for_creator_edit",
        "readiness": _readiness(
            status=readiness_status,
            missing=missing,
            unresolved=unresolved,
        ),
        "target_runtime": "9 seconds",
        "creative_narrative_objective": "Communicate the core idea clearly.",
        "production_constraints": ["Keep visuals restrained."],
        "ordered_edit_sequence": []
        if readiness_status != "ready_for_editing_package"
        else [
            _edit_item(1, asset_reference),
            _edit_item(2, SECOND_ASSET_ID, dialogue=""),
        ],
        "audio_plan": "Use the listed dialogue, SFX, ambience, and music cues.",
        "music_plan": "Use sparse cueing that follows the storyboard beats.",
        "continuity_notes": ["Match approved storyboard continuity."],
        "unresolved_notes": [],
        "provenance_references": [
            f"storyboard:{STORYBOARD_ID}:v1",
            f"asset:{ASSET_ID}",
            f"asset:{SECOND_ASSET_ID}",
        ],
        "governance_boundary": POST_PRODUCTION_GOVERNANCE_BOUNDARY,
        "non_fabrication_statement": NON_FABRICATION_STATEMENT,
    }


def _post_report(
    *,
    memory: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "post_production",
        "runtime": {"clickhouse_writes_performed": False},
        "validation": {},
        "production_memory": memory or _post_production_memory(),
        "structured_output": output or _valid_post_production_output(),
    }


class PostProductionGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_approved_storyboard_fails_closed(self) -> None:
        memory = _post_production_memory(storyboard=None)
        memory["latest_approved_storyboard"] = None
        memory["storyboard_panels"] = []

        with patch.object(
            refinement_agent,
            "retrieve_post_production_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(),
        ) as run_agent:
            with self.assertRaises(PostProductionContextRequiredError):
                await refinement_agent.run_post_production_agent(PROJECT_ID)

        run_agent.assert_not_called()

    def test_pending_or_rejected_candidates_do_not_count_as_approved_assets(self) -> None:
        memory = _post_production_memory(assets=[])
        output = _valid_post_production_output(asset_reference=CANDIDATE_ID)

        with self.assertRaises(RuntimeError):
            refinement_agent._validate_post_production_package(
                _post_report(memory=memory, output=output)
            )

    def test_approved_assets_are_mapped_to_storyboard_requirements(self) -> None:
        report = _post_report()

        refinement_agent._validate_post_production_package(report)

        package = PostProductionPackage.model_validate(report["structured_output"])
        self.assertEqual(
            package.readiness.approved_asset_coverage_per_shot[0].coverage_status,
            "covered",
        )
        self.assertEqual(
            package.ordered_edit_sequence[0].approved_asset_references,
            [ASSET_ID],
        )

    def test_missing_required_asset_returns_not_ready_missing_assets(self) -> None:
        output = _valid_post_production_output(
            readiness_status="not_ready_missing_assets",
            missing=["panel 2 approved payoff plate"],
        )

        refinement_agent._validate_post_production_package(
            _post_report(output=output)
        )
        package = PostProductionPackage.model_validate(output)
        self.assertEqual(
            package.readiness.readiness_status,
            "not_ready_missing_assets",
        )
        self.assertEqual(package.readiness.return_to_stage, "generate_assets")
        self.assertEqual(package.ordered_edit_sequence, [])

    def test_unresolved_qc_issue_returns_not_ready_status(self) -> None:
        output = _valid_post_production_output(
            readiness_status="not_ready_unresolved_qc",
            unresolved=["candidate pending human QC decision"],
        )

        refinement_agent._validate_post_production_package(
            _post_report(output=output)
        )
        package = PostProductionPackage.model_validate(output)
        self.assertEqual(
            package.readiness.readiness_status,
            "not_ready_unresolved_qc",
        )
        self.assertEqual(package.readiness.return_to_stage, "quality_control")


class PostProductionPackageContractTests(unittest.TestCase):
    def test_ready_production_returns_structured_package(self) -> None:
        package = PostProductionPackage.model_validate(
            _valid_post_production_output()
        )

        self.assertEqual(package.package_status, "instructions_for_creator_edit")
        self.assertEqual(
            package.readiness.readiness_status,
            "ready_for_editing_package",
        )
        self.assertEqual(len(package.ordered_edit_sequence), 2)

    def test_ordered_edit_sequence_preserves_storyboard_order(self) -> None:
        package = PostProductionPackage.model_validate(
            _valid_post_production_output()
        )

        self.assertEqual(
            [item.panel_shot_number for item in package.ordered_edit_sequence],
            [1, 2],
        )

    def test_package_contains_editing_audio_music_timing_and_continuity_fields(self) -> None:
        package = PostProductionPackage.model_validate(
            _valid_post_production_output()
        )
        item = package.ordered_edit_sequence[0]

        self.assertEqual(item.intended_duration, "5 seconds")
        self.assertTrue(item.dialogue)
        self.assertTrue(item.sound_effects)
        self.assertTrue(item.ambience)
        self.assertTrue(item.music_cue)
        self.assertTrue(item.transition_into_shot)
        self.assertTrue(item.transition_out_of_shot)
        self.assertTrue(item.editorial_movement_camera_notes)
        self.assertTrue(item.continuity_notes)

    def test_package_references_only_approved_asset_state(self) -> None:
        pending_asset = _approved_asset()
        pending_asset["approval_status"] = "pending"
        report = _post_report(memory=_post_production_memory(assets=[pending_asset]))

        with self.assertRaises(RuntimeError):
            refinement_agent._validate_post_production_package(report)

    def test_no_rendered_or_edited_media_fields_are_allowed(self) -> None:
        payload = _valid_post_production_output()
        payload["rendered_video_uri"] = "file://not-created.mp4"

        with self.assertRaises(ValidationError):
            PostProductionPackage.model_validate(payload)

    def test_gemini_cannot_claim_editing_is_complete(self) -> None:
        output = _valid_post_production_output()
        output["audio_plan"] = "Editing complete and ready to publish."

        with self.assertRaises(RuntimeError):
            refinement_agent._validate_post_production_package(
                _post_report(output=output)
            )


class PostProductionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_post_production_uses_mcp_retrieval_path(self) -> None:
        memory = _post_production_memory()
        report = _post_report(memory=memory)

        with patch.object(
            refinement_agent,
            "retrieve_post_production_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ) as retrieve_memory, patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(return_value=report),
        ) as run_agent:
            result = await refinement_agent.run_post_production_agent(PROJECT_ID)

        retrieve_memory.assert_called_once_with(project_id=PROJECT_ID)
        self.assertEqual(run_agent.call_args.kwargs["stage"], StudioOneStage.POST_PRODUCTION)
        self.assertEqual(
            run_agent.call_args.kwargs["output_schema"],
            PostProductionPackage,
        )
        self.assertIsNotNone(run_agent.call_args.kwargs["memory_retriever"])
        self.assertEqual(
            result["validation"]["agent_memory_retrieval_path"],
            "official_mcp_clickhouse",
        )
        self.assertFalse(result["validation"]["video_rendered"])

    async def test_service_returns_package_without_persistence_writer(self) -> None:
        calls: list[dict[str, Any]] = []

        async def fake_runner(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return _post_report()

        service = PostProductionService(post_production_runner=fake_runner)
        result = await service.prepare_editing_package(
            PostProductionRequest(project_id=PROJECT_ID)
        )

        self.assertEqual(calls, [{"project_id": PROJECT_ID}])
        self.assertEqual(result.stage, "post_production")
        self.assertEqual(result.package["stage"], "post_production")


class PostProductionMcpTests(unittest.TestCase):
    def test_post_production_mcp_queries_are_read_only_and_authoritative(self) -> None:
        asset_query = _approved_assets_for_storyboard_query(PROJECT_ID, "test_db")
        qc_query = _unresolved_qc_issues_query(PROJECT_ID, "test_db")

        self.assertIn("FROM `test_db`.`assets` AS a", asset_query)
        self.assertIn("LEFT JOIN `test_db`.`external_asset_intake` AS i", asset_query)
        self.assertIn("LEFT JOIN `test_db`.`generation_packages` AS p", asset_query)
        self.assertIn("a.approval_status = 'approved'", asset_query)
        self.assertIn("a.authority_level = 'approved_production_state'", asset_query)
        self.assertIn("storyboard_panel_shot_reference", asset_query)
        self.assertIn("qc_status IN", qc_query)
        self.assertIn("intake_status != 'promoted_to_assets'", qc_query)

    def test_post_production_reasoning_uses_mcp_not_direct_clickhouse(self) -> None:
        source = inspect.getsource(refinement_agent)

        self.assertIn("retrieve_post_production_memory_bundle", source)
        self.assertNotIn("clickhouse_connect", source)
        self.assertNotIn("ClickHouseQualityControlPersistence", source)

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
