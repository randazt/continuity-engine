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
    PUBLISH_GOVERNANCE_BOUNDARY,
    PublishContextRequiredError,
    PublishPackage,
)
from studio_one.integrations import clickhouse_mcp
from studio_one.integrations.clickhouse_mcp import retrieve_publish_memory_bundle
from studio_one.services.publish_service import PublishRequest
from studio_one.services.publish_service import PublishService
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS
from studio_one.workflow.stages import IMPLEMENTED_STAGE_IDENTIFIERS
from studio_one.workflow.stages import StudioOneStage


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
STORYBOARD_ID = "22222222-2222-4222-8222-222222222222"
ASSET_ID = "33333333-3333-4333-8333-333333333333"
SECOND_ASSET_ID = "44444444-4444-4444-8444-444444444444"
FINAL_EDIT_REFERENCE = "creator-final-edit://exports/project-final-v1.mp4"


def _storyboard_json() -> str:
    return json.dumps(
        {
            "panels": [
                {
                    "panel_shot_number": 1,
                    "duration": "5 seconds",
                    "story_purpose": "Establish the opening idea.",
                    "dialogue": "Opening line.",
                    "sound_effects": ["Soft room tone"],
                    "ambience": "Quiet interior.",
                    "music_direction": "Sparse pulse.",
                    "asset_requirements": ["approved opening plate"],
                },
                {
                    "panel_shot_number": 2,
                    "duration": "4 seconds",
                    "story_purpose": "Pay off the setup.",
                    "dialogue": "",
                    "sound_effects": ["Small impact"],
                    "ambience": "Low exterior bed.",
                    "music_direction": "Resolve the cue.",
                    "asset_requirements": ["approved payoff plate"],
                },
            ]
        }
    )


def _publish_memory(
    *,
    storyboard: dict[str, Any] | None = None,
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
            "production_constraints_applied": ["Keep visuals restrained."],
            "unresolved_issues": [],
            "storyboard_json": _storyboard_json(),
        }
    return {
        "project": {
            "project_id": PROJECT_ID,
            "title": "Creator Project",
            "production_constraints": "Keep visuals restrained.",
            "initial_creative_intent": "Make a focused short-form production.",
        },
        "latest_approved_storyboard": latest_storyboard,
        "storyboard_panels": json.loads(latest_storyboard["storyboard_json"]).get(
            "panels",
            [],
        )
        if latest_storyboard
        else [],
        "approved_assets": [
            {
                "asset_id": ASSET_ID,
                "project_id": PROJECT_ID,
                "approval_status": "approved",
                "authority_level": "approved_production_state",
                "external_asset_reference": "creator-submitted://opening.png",
                "source_reference": "external_asset_candidate:opening",
                "storyboard_panel_shot_reference": "panel 1",
            },
            {
                "asset_id": SECOND_ASSET_ID,
                "project_id": PROJECT_ID,
                "approval_status": "approved",
                "authority_level": "approved_production_state",
                "external_asset_reference": "creator-submitted://payoff.png",
                "source_reference": "external_asset_candidate:payoff",
                "storyboard_panel_shot_reference": "panel 2",
            },
        ],
        "unresolved_qc_issues": unresolved_qc or [],
        "decision_log_entries": [
            {
                "decision_id": "55555555-5555-4555-8555-555555555555",
                "decision": "approved",
                "affected_table": "storyboards",
            }
        ],
        "assets_count": 2,
    }


def _readiness(
    *,
    status: str = "ready_for_publish_package",
    final_edit_supplied: bool = True,
    unresolved: list[str] | None = None,
    missing_metadata: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "approved_storyboard_present": True,
        "final_edit_context_supplied": final_edit_supplied,
        "final_edit_claim_is_creator_supplied": final_edit_supplied,
        "unresolved_qc_issues": unresolved or [],
        "missing_required_metadata": missing_metadata or [],
        "readiness_status": status,
        "return_to_stage": "post_production"
        if status
        in {
            "not_ready_missing_final_edit_context",
            "not_ready_missing_required_metadata",
        }
        else "quality_control"
        if status == "not_ready_unresolved_qc"
        else "",
        "notes": ["Creator approval is still required before manual posting."],
    }


def _text_option(option_id: str, text: str) -> dict[str, Any]:
    return {
        "option_id": option_id,
        "text": text,
        "rationale": "Grounded in the approved storyboard and final edit context.",
        "source_provenance_references": [f"storyboard:{STORYBOARD_ID}:v1"],
    }


def _keyword_option() -> dict[str, Any]:
    return {
        "option_id": "seo-1",
        "keywords": ["creator workflow", "production memory", "short film"],
        "rationale": "Reflects project intent and storyboard language.",
        "source_provenance_references": [f"storyboard:{STORYBOARD_ID}:v1"],
    }


def _hashtag_option() -> dict[str, Any]:
    return {
        "option_id": "hashtags-1",
        "hashtags": ["#CreatorWorkflow", "#ProductionMemory", "#ShortFilm"],
        "rationale": "Uses generic discoverability terms.",
        "source_provenance_references": [f"storyboard:{STORYBOARD_ID}:v1"],
    }


def _platform_option(platform_variant: str = "short-form social") -> dict[str, Any]:
    return {
        "platform_variant": platform_variant,
        "recommended_title": "Studio Memory in Motion",
        "short_caption": "A concise creator-approved production story.",
        "long_description": (
            "A creator-ready description based on the approved storyboard, "
            "approved assets, and creator-supplied final edit reference."
        ),
        "hashtags": ["#CreatorWorkflow", "#ProductionMemory"],
        "cta": "Review the package, then publish manually when approved.",
        "seo_terms": ["creator workflow", "production memory"],
        "metadata_notes": ["Provider-neutral copy; no posting integration assumed."],
        "source_provenance_references": [f"storyboard:{STORYBOARD_ID}:v1"],
    }


def _valid_publish_output(
    *,
    readiness_status: str = "ready_for_publish_package",
    final_edit_reference: str | None = FINAL_EDIT_REFERENCE,
    final_edit_supplied: bool = True,
    unresolved: list[str] | None = None,
    missing_metadata: list[str] | None = None,
    platform_variant: str = "short-form social",
) -> dict[str, Any]:
    return {
        "stage": "publish",
        "project_id": PROJECT_ID,
        "approved_storyboard_id": STORYBOARD_ID,
        "approved_storyboard_version": 1,
        "final_edit_reference": final_edit_reference,
        "publishing_readiness": _readiness(
            status=readiness_status,
            final_edit_supplied=final_edit_supplied,
            unresolved=unresolved,
            missing_metadata=missing_metadata,
        ),
        "title_options": [
            _text_option("title-1", "Studio Memory in Motion"),
            _text_option("title-2", "When the Studio Remembers"),
        ],
        "seo_keyword_options": [_keyword_option()],
        "caption_options": [
            _text_option("caption-1", "A creator-ready caption for manual posting.")
        ],
        "description_options": [
            _text_option(
                "description-1",
                "A creator-ready long description grounded in production memory.",
            )
        ],
        "hashtag_options": [_hashtag_option()],
        "platform_copy_options": [_platform_option(platform_variant)],
        "thumbnail_key_art_guidance": [
            "Use approved key art from the opening plate when preparing a thumbnail."
        ],
        "accessibility_caption_notes": [
            "Use creator-reviewed captions for spoken dialogue before manual posting."
        ],
        "recommended_options": {
            "title_option_id": "title-1",
            "caption_option_id": "caption-1",
            "description_option_id": "description-1",
            "hashtag_option_id": "hashtags-1",
            "rationale": "This set is concise and aligned with the final edit context.",
        },
        "provenance_references": [
            f"storyboard:{STORYBOARD_ID}:v1",
            f"asset:{ASSET_ID}",
            f"asset:{SECOND_ASSET_ID}",
            "mcp:publish-memory",
            f"final_edit:{FINAL_EDIT_REFERENCE}",
        ],
        "governance_boundary": PUBLISH_GOVERNANCE_BOUNDARY,
        "non_fabrication_statement": NON_FABRICATION_STATEMENT,
    }


def _publish_report(
    *,
    memory: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    final_edit_reference: str | None = FINAL_EDIT_REFERENCE,
    final_edit_is_complete: bool = True,
    requested_platforms: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "stage": "publish",
        "runtime": {"clickhouse_writes_performed": False},
        "validation": {},
        "request_context": {
            "final_edit_reference": final_edit_reference,
            "final_edit_is_complete": final_edit_is_complete,
            "final_edit_notes": "Creator confirmed this is the final edit.",
            "required_metadata": {},
            "requested_platforms": requested_platforms or [],
            "post_production_package_supplied": False,
        },
        "production_memory": memory or _publish_memory(),
        "structured_output": output or _valid_publish_output(),
    }


class PublishGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_approved_storyboard_fails_closed(self) -> None:
        memory = _publish_memory()
        memory["latest_approved_storyboard"] = None
        memory["storyboard_panels"] = []

        with patch.object(
            refinement_agent,
            "retrieve_publish_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ), patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(),
        ) as run_agent:
            with self.assertRaises(PublishContextRequiredError):
                await refinement_agent.run_publish_agent(
                    PROJECT_ID,
                    final_edit_reference=FINAL_EDIT_REFERENCE,
                    final_edit_is_complete=True,
                )

        run_agent.assert_not_called()

    def test_unresolved_qc_prevents_ready_state(self) -> None:
        memory = _publish_memory(
            unresolved_qc=[
                {
                    "external_asset_candidate_id": "66666666-6666-4666-8666-666666666666",
                    "qc_status": "qc_review_pending_human_decision",
                }
            ]
        )

        with self.assertRaises(RuntimeError):
            refinement_agent._validate_publish_package(
                _publish_report(memory=memory, output=_valid_publish_output())
            )

        output = _valid_publish_output(
            readiness_status="not_ready_unresolved_qc",
            unresolved=["candidate pending human QC decision"],
        )
        refinement_agent._validate_publish_package(
            _publish_report(memory=memory, output=output)
        )
        package = PublishPackage.model_validate(output)
        self.assertEqual(
            package.publishing_readiness.readiness_status,
            "not_ready_unresolved_qc",
        )

    def test_missing_required_final_edit_context_can_produce_not_ready_result(self) -> None:
        output = _valid_publish_output(
            readiness_status="not_ready_missing_final_edit_context",
            final_edit_reference=None,
            final_edit_supplied=False,
        )

        refinement_agent._validate_publish_package(
            _publish_report(
                output=output,
                final_edit_reference=None,
                final_edit_is_complete=False,
            )
        )
        package = PublishPackage.model_validate(output)
        self.assertEqual(
            package.publishing_readiness.readiness_status,
            "not_ready_missing_final_edit_context",
        )


class PublishPackageContractTests(unittest.TestCase):
    def test_valid_production_state_produces_structured_publish_package(self) -> None:
        report = _publish_report()

        refinement_agent._validate_publish_package(report)
        package = PublishPackage.model_validate(report["structured_output"])

        self.assertEqual(package.stage, "publish")
        self.assertEqual(
            package.publishing_readiness.readiness_status,
            "ready_for_publish_package",
        )
        self.assertEqual(package.final_edit_reference, FINAL_EDIT_REFERENCE)

    def test_package_contains_title_options(self) -> None:
        package = PublishPackage.model_validate(_valid_publish_output())

        self.assertGreaterEqual(len(package.title_options), 1)
        self.assertTrue(package.title_options[0].text)

    def test_package_contains_seo_options(self) -> None:
        package = PublishPackage.model_validate(_valid_publish_output())

        self.assertGreaterEqual(len(package.seo_keyword_options), 1)
        self.assertTrue(package.seo_keyword_options[0].keywords)

    def test_package_contains_caption_options(self) -> None:
        package = PublishPackage.model_validate(_valid_publish_output())

        self.assertGreaterEqual(len(package.caption_options), 1)
        self.assertTrue(package.caption_options[0].text)

    def test_package_contains_description_options(self) -> None:
        package = PublishPackage.model_validate(_valid_publish_output())

        self.assertGreaterEqual(len(package.description_options), 1)
        self.assertTrue(package.description_options[0].text)

    def test_package_contains_hashtag_options(self) -> None:
        package = PublishPackage.model_validate(_valid_publish_output())

        self.assertGreaterEqual(len(package.hashtag_options), 1)
        self.assertTrue(package.hashtag_options[0].hashtags)

    def test_platform_copy_remains_provider_neutral_unless_requested(self) -> None:
        generic_report = _publish_report()
        refinement_agent._validate_publish_package(generic_report)

        named_platform_output = _valid_publish_output(platform_variant="TikTok")
        with self.assertRaises(RuntimeError):
            refinement_agent._validate_publish_package(
                _publish_report(output=named_platform_output)
            )

        refinement_agent._validate_publish_package(
            _publish_report(
                output=named_platform_output,
                requested_platforms=["TikTok"],
            )
        )

    def test_no_published_url_or_upload_fields_are_allowed(self) -> None:
        payload = _valid_publish_output()
        payload["published_url"] = "https://example.invalid/live"

        with self.assertRaises(ValidationError):
            PublishPackage.model_validate(payload)

    def test_gemini_cannot_claim_content_was_published(self) -> None:
        output = _valid_publish_output()
        output["caption_options"][0]["text"] = "The video has been published."

        with self.assertRaises(RuntimeError):
            refinement_agent._validate_publish_package(
                _publish_report(output=output)
            )

    def test_missing_required_metadata_can_block_ready_state(self) -> None:
        output = _valid_publish_output(
            readiness_status="not_ready_missing_required_metadata",
            missing_metadata=["final runtime", "content format"],
        )

        refinement_agent._validate_publish_package(
            _publish_report(output=output)
        )
        package = PublishPackage.model_validate(output)
        self.assertEqual(
            package.publishing_readiness.readiness_status,
            "not_ready_missing_required_metadata",
        )


class PublishRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_publish_uses_mcp_retrieval_path(self) -> None:
        memory = _publish_memory()
        report = _publish_report(memory=memory)

        with patch.object(
            refinement_agent,
            "retrieve_publish_memory_bundle",
            new=AsyncMock(return_value={"production_memory": memory}),
        ) as retrieve_memory, patch.object(
            refinement_agent,
            "_run_stage_agent",
            new=AsyncMock(return_value=report),
        ) as run_agent:
            result = await refinement_agent.run_publish_agent(
                PROJECT_ID,
                final_edit_reference=FINAL_EDIT_REFERENCE,
                final_edit_is_complete=True,
            )

        retrieve_memory.assert_called_once_with(project_id=PROJECT_ID)
        self.assertEqual(run_agent.call_args.kwargs["stage"], StudioOneStage.PUBLISH)
        self.assertEqual(run_agent.call_args.kwargs["output_schema"], PublishPackage)
        self.assertIsNotNone(run_agent.call_args.kwargs["memory_retriever"])
        self.assertEqual(
            result["validation"]["agent_memory_retrieval_path"],
            "official_mcp_clickhouse",
        )
        self.assertFalse(result["validation"]["external_publishing_api_called"])
        self.assertFalse(result["validation"]["media_upload_performed"])
        self.assertFalse(result["validation"]["content_published"])

    async def test_service_returns_package_without_persistence_writer(self) -> None:
        calls: list[dict[str, Any]] = []

        async def fake_runner(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return _publish_report()

        service = PublishService(publish_runner=fake_runner)
        result = await service.prepare_publish_package(
            PublishRequest(
                project_id=PROJECT_ID,
                final_edit_reference=FINAL_EDIT_REFERENCE,
                final_edit_is_complete=True,
                requested_platforms=[],
            )
        )

        self.assertEqual(
            calls,
            [
                {
                    "project_id": PROJECT_ID,
                    "final_edit_reference": FINAL_EDIT_REFERENCE,
                    "final_edit_is_complete": True,
                    "final_edit_notes": "",
                    "required_metadata": {},
                    "requested_platforms": [],
                    "post_production_package": None,
                }
            ],
        )
        self.assertEqual(result.stage, "publish")
        self.assertEqual(result.package["stage"], "publish")


class PublishMcpTests(unittest.TestCase):
    def test_publish_bundle_uses_official_mcp_path(self) -> None:
        source = inspect.getsource(clickhouse_mcp)

        self.assertIn("retrieve_publish_memory_bundle", source)
        self.assertIn("mcp_clickhouse.main", source)
        self.assertIn('"CLICKHOUSE_ALLOW_WRITE_ACCESS": "false"', source)
        self.assertIn("_project_query", source)
        self.assertIn("_latest_approved_storyboard_query", source)
        self.assertIn("_approved_assets_for_storyboard_query", source)
        self.assertIn("_unresolved_qc_issues_query", source)
        self.assertIn("_project_decisions_query", source)

    def test_publish_reasoning_uses_mcp_not_direct_clickhouse(self) -> None:
        source = inspect.getsource(refinement_agent)

        self.assertIn("retrieve_publish_memory_bundle", source)
        self.assertIn("retrieve_publish_stage_memory", source)
        self.assertNotIn("clickhouse_connect", source)

    def test_publish_mcp_function_is_importable(self) -> None:
        self.assertTrue(callable(retrieve_publish_memory_bundle))

    def test_no_non_google_ai_runtime_provider_is_introduced(self) -> None:
        runtime_source = "\n".join(
            [
                inspect.getsource(refinement_agent),
                inspect.getsource(clickhouse_mcp),
            ]
        )

        self.assertNotIn("requests.", runtime_source)
        self.assertNotIn("httpx.", runtime_source)
        self.assertNotIn("openai.", runtime_source)
        self.assertNotIn("anthropic", runtime_source)
        self.assertNotIn("imagegen", runtime_source)
        self.assertNotIn("tts_provider", runtime_source)

    def test_no_publishing_or_upload_api_is_called(self) -> None:
        runtime_source = "\n".join(
            [
                inspect.getsource(refinement_agent),
                inspect.getsource(clickhouse_mcp),
            ]
        )

        self.assertNotIn("publish_to_", runtime_source)
        self.assertNotIn("upload_media", runtime_source)
        self.assertNotIn("schedule_post", runtime_source)
        self.assertNotIn("click_publish", runtime_source)

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
