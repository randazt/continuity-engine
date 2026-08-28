from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from pydantic import ValidationError

from studio_one.agents import refinement_agent
from studio_one.agents.refinement_agent import (
    ASSET_STATE_BOUNDARY,
    GENERATE_ASSETS_GOVERNANCE_BOUNDARY,
    PROVIDER_SELECTION_BOUNDARY,
    ApprovedStoryboardRequiredError,
    GenerateAssetsPackage,
)
from studio_one.integrations import clickhouse_mcp
from studio_one.integrations.clickhouse_mcp import _assets_inventory_query
from studio_one.integrations.clickhouse_mcp import _latest_approved_storyboard_query
from studio_one.services.generate_assets_service import GenerateAssetsRequest
from studio_one.services.generate_assets_service import GenerateAssetsService
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS
from studio_one.workflow.stages import IMPLEMENTED_STAGE_IDENTIFIERS
from studio_one.workflow.stages import StudioOneStage


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
STORYBOARD_ID = "22222222-2222-4222-8222-222222222222"


def approved_storyboard_memory(assets: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "project": {
            "project_id": PROJECT_ID,
            "title": "Creator Project",
            "production_constraints": "Use creator-approved visual constraints.",
        },
        "review_queue": None,
        "decision_log": None,
        "latest_approved_storyboard": {
            "storyboard_id": STORYBOARD_ID,
            "project_id": PROJECT_ID,
            "storyboard_version": 1,
            "status": "approved",
            "approval_status": "approved",
            "authority_level": "approved_production_state",
            "storyboard_json": "{}",
        },
        "assets": assets or [],
        "assets_count": len(assets or []),
    }


def valid_generate_assets_output(
    reusable_existing_assets: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "stage": "generate_assets",
        "project_id": PROJECT_ID,
        "approved_storyboard_id": STORYBOARD_ID,
        "approved_storyboard_version": 1,
        "package_status": "instructions_for_creator",
        "asset_requirements": [
            {
                "requirement_id": "panel-1-background",
                "storyboard_reference": "panel 1",
                "narrative_purpose": "Establish the scene.",
                "asset_requirement_type": "background",
                "description": "Primary visual background.",
                "classification": "missing_asset",
                "reuse_assessment": "No reusable asset was found.",
                "source_provenance_references": ["storyboard:1:panel:1"],
            }
        ],
        "reusable_existing_assets": reusable_existing_assets or [],
        "missing_assets": [
            {
                "requirement_id": "panel-1-background",
                "storyboard_reference": "panel 1",
                "asset_requirement_type": "background",
                "description": "Primary visual background.",
                "reason_no_reusable_asset_found": "No reusable assets were found in project inventory.",
                "source_provenance_references": ["storyboard:1:panel:1"],
            }
        ],
        "image_prompt_packages": [
            {
                "project_id": PROJECT_ID,
                "approved_storyboard_id": STORYBOARD_ID,
                "approved_storyboard_version": 1,
                "storyboard_reference": "panel 1",
                "narrative_purpose": "Establish the scene.",
                "asset_requirement_type": "background",
                "reuse_assessment": "No reusable asset was found.",
                "production_constraints": ["Use creator-approved visual constraints."],
                "composition": "Centered subject with clear foreground and background.",
                "camera_framing": "Wide frame.",
                "environment": "Creator-defined setting.",
                "lighting": "Soft key light.",
                "subject_character_requirements": "Use only approved subject requirements.",
                "continuity_requirements": ["Match approved storyboard continuity."],
                "technical_requirements": ["Usable as a source still."],
                "positive_image_prompt": "Provider-neutral image instructions.",
                "negative_avoid_instructions": "Avoid unapproved characters and logos.",
                "source_provenance_references": ["storyboard:1:panel:1"],
            }
        ],
        "video_prompt_packages": [
            {
                "storyboard_reference": "panel 1",
                "approved_still_image_dependency": "Use the creator-approved still when available.",
                "starting_frame_intent": "Start on the established composition.",
                "ending_frame_intent": "End after a subtle change in emphasis.",
                "motion_description": "Subtle environmental motion.",
                "camera_motion": "Slow push-in.",
                "environmental_motion": "Small background movement.",
                "character_subject_motion": "No unapproved subject motion.",
                "duration": "5 seconds",
                "continuity_requirements": ["Preserve storyboard continuity."],
                "video_generation_prompt": "Provider-neutral motion instructions.",
                "source_provenance_references": ["storyboard:1:panel:1"],
            }
        ],
        "dialogue_audio_handoffs": [
            {
                "storyboard_reference": "panel 1",
                "speaker_role": "Narrator",
                "exact_dialogue": "Exact creator-approved dialogue.",
                "emotion": "Calm",
                "pacing": "Measured",
                "delivery": "Natural",
                "pauses": "Short pause after first phrase.",
                "breathing": "Natural breaths only.",
                "emphasis": "Emphasize the final word.",
                "continuity_voice_notes": "Keep voice consistent if externally produced.",
            }
        ],
        "sound_music_handoffs": [
            {
                "storyboard_reference": "panel 1",
                "sound_effects": ["Room tone"],
                "ambience": "Quiet interior ambience.",
                "music_direction": "Sparse music bed.",
                "source_provenance_references": ["storyboard:1:panel:1"],
            }
        ],
        "provenance_references": ["storyboard:1"],
        "governance_boundary": GENERATE_ASSETS_GOVERNANCE_BOUNDARY,
        "asset_state_boundary": ASSET_STATE_BOUNDARY,
        "provider_selection_boundary": PROVIDER_SELECTION_BOUNDARY,
    }


class GenerateAssetsGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_approved_storyboard_fails_closed(self) -> None:
        memory = {
            "production_memory": {
                "project": {"project_id": PROJECT_ID},
                "review_queue": None,
                "latest_approved_storyboard": None,
                "assets": [],
                "assets_count": 0,
            }
        }

        with patch.object(
            refinement_agent,
            "retrieve_project_memory_bundle",
            new=AsyncMock(return_value=memory),
        ), patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(),
        ) as run_agent:
            with self.assertRaises(ApprovedStoryboardRequiredError):
                await refinement_agent.run_generate_assets_agent(PROJECT_ID)

        run_agent.assert_not_called()

    async def test_pending_storyboard_candidate_alone_is_insufficient(self) -> None:
        memory = {
            "production_memory": {
                "project": {"project_id": PROJECT_ID},
                "review_queue": {
                    "review_type": "storyboard_candidate",
                    "status": "pending",
                    "proposed_state_change": "{}",
                },
                "latest_approved_storyboard": None,
                "assets": [],
                "assets_count": 0,
            }
        }

        with patch.object(
            refinement_agent,
            "retrieve_project_memory_bundle",
            new=AsyncMock(return_value=memory),
        ), patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(),
        ) as run_agent:
            with self.assertRaises(ApprovedStoryboardRequiredError):
                await refinement_agent.run_generate_assets_agent(PROJECT_ID)

        run_agent.assert_not_called()


class GenerateAssetsMcpTests(unittest.TestCase):
    def test_latest_approved_storyboard_is_retrieved_through_mcp(self) -> None:
        source = inspect.getsource(clickhouse_mcp)

        self.assertIn("_latest_approved_storyboard_query", source)
        self.assertIn("_assets_inventory_query", source)
        self.assertIn("latest_approved_storyboard", source)
        self.assertIn('"assets": _rows(assets_inventory_payload)', source)
        self.assertIn("CLICKHOUSE_ALLOW_WRITE_ACCESS", source)
        self.assertIn('"false"', source)

    def test_approved_storyboard_query_qualifies_authoritative_state_only(self) -> None:
        query = _latest_approved_storyboard_query(PROJECT_ID, "test_db")

        self.assertIn("status = 'approved'", query)
        self.assertIn("approval_status = 'approved'", query)
        self.assertIn("authority_level = 'approved_production_state'", query)
        self.assertIn(
            "ORDER BY storyboard_version DESC, approved_at DESC, storyboard_id DESC",
            query,
        )
        self.assertNotIn("review_queue", query)

    def test_existing_project_assets_are_retrieved_for_reuse_audit(self) -> None:
        query = _assets_inventory_query(PROJECT_ID, "test_db")

        self.assertIn("FROM `test_db`.`assets`", query)
        self.assertIn("WHERE a.project_id =", query)
        self.assertIn("ORDER BY asset_type, name, asset_id", query)
        self.assertIn("reuse_relationship", query)
        self.assertIn("approved_decision_id", query)

    def test_stage_instruction_requires_reuse_before_missing_assets(self) -> None:
        instruction = refinement_agent._stage_task_instruction(
            StudioOneStage.GENERATE_ASSETS
        )

        self.assertIn("Use production_memory.assets", instruction)
        self.assertIn("Evaluate reuse before declaring any missing asset", instruction)
        self.assertIn("Do not fabricate reusable assets", instruction)
        self.assertIn("Prompts and handoff instructions are not assets", instruction)


class GenerateAssetsPackageContractTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_asset_inventory_yields_no_fabricated_reuse_candidates(self) -> None:
        report = {
            "production_memory": approved_storyboard_memory(assets=[]),
            "structured_output": valid_generate_assets_output(),
        }

        refinement_agent._validate_generate_assets_package(report)
        package = GenerateAssetsPackage.model_validate(report["structured_output"])
        self.assertEqual(package.reusable_existing_assets, [])
        self.assertEqual(package.asset_requirements[0].classification, "missing_asset")

    def test_reuse_candidates_cannot_be_fabricated_from_empty_inventory(self) -> None:
        report = {
            "production_memory": approved_storyboard_memory(assets=[]),
            "structured_output": valid_generate_assets_output(
                reusable_existing_assets=[
                    {
                        "requirement_id": "panel-1-background",
                        "storyboard_reference": "panel 1",
                        "asset_id": "33333333-3333-4333-8333-333333333333",
                        "asset_type": "background",
                        "name": "Existing background",
                        "reuse_rationale": "Looks usable.",
                        "continuity_notes": "Check continuity.",
                        "source_provenance_references": ["asset:existing"],
                    }
                ]
            ),
        }

        with self.assertRaises(RuntimeError):
            refinement_agent._validate_generate_assets_package(report)

    def test_image_prompts_are_not_assets(self) -> None:
        package = GenerateAssetsPackage.model_validate(valid_generate_assets_output())

        self.assertEqual(package.image_prompt_packages[0].positive_image_prompt, "Provider-neutral image instructions.")
        self.assertNotIn("generated_assets", GenerateAssetsPackage.model_fields)
        self.assertIn("generation_prompt", package.asset_state_boundary)

    def test_video_prompts_are_not_assets(self) -> None:
        package = GenerateAssetsPackage.model_validate(valid_generate_assets_output())

        self.assertEqual(package.video_prompt_packages[0].video_generation_prompt, "Provider-neutral motion instructions.")
        self.assertNotIn("video_assets", GenerateAssetsPackage.model_fields)

    def test_dialogue_tts_instructions_are_not_audio_assets(self) -> None:
        package = GenerateAssetsPackage.model_validate(valid_generate_assets_output())

        self.assertEqual(package.dialogue_audio_handoffs[0].exact_dialogue, "Exact creator-approved dialogue.")
        self.assertNotIn("audio_assets", GenerateAssetsPackage.model_fields)

    def test_gemini_cannot_mark_assets_generated_or_qc_approved(self) -> None:
        payload = valid_generate_assets_output()
        payload["generated_assets"] = []
        payload["qc_approved_assets"] = []

        with self.assertRaises(ValidationError):
            GenerateAssetsPackage.model_validate(payload)

    def test_no_external_generation_provider_is_called_by_runtime(self) -> None:
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

    async def test_package_creation_inserts_zero_asset_rows(self) -> None:
        calls: list[dict[str, object]] = []

        async def fake_runner(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "stage": "generate_assets",
                "runtime": {"clickhouse_writes_performed": False},
                "validation": {
                    "asset_rows_created": 0,
                    "external_generation_provider_called": False,
                },
                "structured_output": valid_generate_assets_output(),
            }

        service = GenerateAssetsService(generate_assets_runner=fake_runner)
        result = await service.generate_assets_package(
            GenerateAssetsRequest(project_id=PROJECT_ID)
        )

        self.assertEqual(calls, [{"project_id": PROJECT_ID}])
        self.assertEqual(result.stage, "generate_assets")
        self.assertEqual(result.package["validation"]["asset_rows_created"], 0)

    def test_exactly_seven_canonical_workflow_stages_remain(self) -> None:
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
