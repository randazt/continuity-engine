from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import unittest

from fastapi.testclient import TestClient

from studio_one.integrations.clickhouse_persistence import (
    CreatedExternalAssetCandidateRecord,
    CreatedProjectRecord,
    CreatedQualityControlReviewRecord,
    CreatedStoryboardReviewRecord,
    ProjectCreateRecord,
    StoryboardReviewDecisionResult,
)
from studio_one.services.project_service import ProjectService
from studio_one.web.app import StudioOneWebDependencies
from studio_one.web.app import create_app
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS
from studio_one.workflow.stages import StudioOneStage


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
STORYBOARD_ID = "22222222-2222-4222-8222-222222222222"
REVIEW_ID = "33333333-3333-4333-8333-333333333333"
CANDIDATE_ID = "44444444-4444-4444-8444-444444444444"
QC_REVIEW_ID = "55555555-5555-4555-8555-555555555555"
ASSET_ID = "66666666-6666-4666-8666-666666666666"


class FakeProjectWriter:
    def __init__(self) -> None:
        self.records: list[ProjectCreateRecord] = []

    def create_project(self, record: ProjectCreateRecord) -> CreatedProjectRecord:
        self.records.append(record)
        return CreatedProjectRecord(
            project_id=PROJECT_ID,
            title=record.title.strip(),
            status="active_in_development",
            current_canon_version="",
            authority_level="creator_supplied_project_context",
            authoritative_source="creator",
            source_reference=record.source_reference,
            source_version=record.source_version,
            approval_status="creator_supplied",
            state_version=1,
            approved_decision_id=None,
            production_constraints=record.production_constraints.strip(),
            initial_creative_intent=record.initial_creative_intent.strip(),
        )


@dataclass(frozen=True)
class ModelResult:
    payload: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return self.payload


class FakeStoryboardService:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []

    def submit_candidate_for_review(
        self,
        request: Any,
    ) -> CreatedStoryboardReviewRecord:
        self.submitted.append(request.model_dump())
        return CreatedStoryboardReviewRecord(
            review_id=REVIEW_ID,
            project_id=request.project_id,
            status="pending",
            review_type="storyboard_candidate",
            proposed_action="approve_storyboard",
            proposed_state_change="{}",
        )

    def decide_review(
        self,
        request: Any,
    ) -> StoryboardReviewDecisionResult:
        self.decisions.append(request.model_dump())
        return StoryboardReviewDecisionResult(
            project_id=request.project_id,
            review_id=request.review_id,
            decision_id="77777777-7777-4777-8777-777777777777",
            decision="approved" if request.action == "approve" else request.action,
            review_status="approved" if request.action == "approve" else request.action,
            storyboard_id=STORYBOARD_ID if request.action == "approve" else None,
            storyboard_version=1 if request.action == "approve" else None,
            storyboard_created=request.action == "approve",
        )


class FakeGenerateAssetsService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate_assets_package(self, request: Any) -> ModelResult:
        self.calls.append(request.project_id)
        return ModelResult(
            {
                "project_id": request.project_id,
                "stage": StudioOneStage.GENERATE_ASSETS.value,
                "package": {
                    "stage": "generate_assets",
                    "package_status": "instructions_for_creator",
                    "image_prompt_packages": [
                        {
                            "storyboard_reference": "panel 1",
                            "prompt": "Creator-facing image prompt.",
                        }
                    ],
                    "asset_state_boundary": (
                        "Instructions only; no media asset is generated or approved."
                    ),
                },
                "persisted_generation_packages": [],
            }
        )


class FakeExternalAssetIntakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def submit_candidate_for_qc(self, request: Any) -> ModelResult:
        self.calls.append(request.model_dump())
        return ModelResult(
            {
                "project_id": request.project_id,
                "stage": StudioOneStage.QUALITY_CONTROL.value,
                "candidate": CreatedExternalAssetCandidateRecord(
                    external_asset_candidate_id=CANDIDATE_ID,
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
                    intake_status="submitted_for_qc",
                    qc_status="pending_qc",
                    authority_level="external_asset_candidate",
                    supersedes_external_asset_candidate_id=None,
                    retry_of_external_asset_candidate_id=None,
                ).__dict__,
            }
        )


class FakeQualityControlService:
    def __init__(self) -> None:
        self.qc_calls: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []

    async def run_quality_control(self, request: Any) -> ModelResult:
        self.qc_calls.append(request.model_dump())
        return ModelResult(
            {
                "project_id": request.project_id,
                "stage": StudioOneStage.QUALITY_CONTROL.value,
                "assessment": {
                    "structured_output": {
                        "recommendation": "recommend_approve",
                        "governance_boundary": (
                            "Gemini recommendation only; human decision required."
                        ),
                    }
                },
                "review": CreatedQualityControlReviewRecord(
                    review_id=QC_REVIEW_ID,
                    project_id=request.project_id,
                    external_asset_candidate_id=request.external_asset_candidate_id,
                    status="pending",
                    review_type="asset_qc",
                    proposed_action="approve_asset",
                    proposed_state_change="{}",
                ).__dict__,
            }
        )

    def decide_quality_control_review(self, request: Any) -> dict[str, Any]:
        self.decisions.append(request.model_dump())
        return {
            "project_id": request.project_id,
            "review_id": request.review_id,
            "external_asset_candidate_id": CANDIDATE_ID,
            "decision_id": "88888888-8888-4888-8888-888888888888",
            "decision": "approved" if request.action == "approve" else request.action,
            "review_status": "approved" if request.action == "approve" else request.action,
            "candidate_qc_status": "approved_for_promotion"
            if request.action == "approve"
            else request.action,
            "candidate_intake_status": "promoted_to_assets"
            if request.action == "approve"
            else "submitted_for_qc",
            "asset_id": ASSET_ID if request.action == "approve" else None,
            "asset_created": request.action == "approve",
        }


class FakePostProductionService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def prepare_editing_package(self, request: Any) -> ModelResult:
        self.calls.append(request.project_id)
        return ModelResult(
            {
                "project_id": request.project_id,
                "stage": StudioOneStage.POST_PRODUCTION.value,
                "package": {
                    "post_production_readiness": "ready_for_editing_package",
                    "final_media_edited": False,
                    "governance_boundary": (
                        "Manual editing instructions only; creator controls final edit."
                    ),
                },
            }
        )


class FakePublishService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def prepare_publish_package(self, request: Any) -> ModelResult:
        self.calls.append(request.model_dump())
        readiness = "ready_for_publish_package"
        if not request.final_edit_is_complete:
            readiness = "not_ready_missing_final_edit_context"
        return ModelResult(
            {
                "project_id": request.project_id,
                "stage": StudioOneStage.PUBLISH.value,
                "package": {
                    "project_id": request.project_id,
                    "approved_storyboard_id": STORYBOARD_ID,
                    "approved_storyboard_version": 1,
                    "final_edit_reference": request.final_edit_reference,
                    "publishing_readiness": {"readiness_status": readiness},
                    "title_options": [
                        {
                            "option_id": "title-1",
                            "text": "Creator-Ready Production Title",
                        }
                    ],
                    "seo_keyword_options": [
                        {"option_id": "seo-1", "keywords": ["production memory"]}
                    ],
                    "caption_options": [
                        {"option_id": "caption-1", "text": "Manual-post caption."}
                    ],
                    "description_options": [
                        {
                            "option_id": "description-1",
                            "text": "Manual-post description.",
                        }
                    ],
                    "hashtag_options": [
                        {"option_id": "hashtags-1", "hashtags": ["#ProductionMemory"]}
                    ],
                    "platform_copy_options": [
                        {
                            "platform_variant": "short-form social",
                            "recommended_title": "Creator-Ready Production Title",
                            "short_caption": "Manual-post caption.",
                            "long_description": "Manual-post description.",
                            "hashtags": ["#ProductionMemory"],
                            "CTA": "Review and publish manually.",
                            "SEO_terms": ["production memory"],
                            "metadata_notes": [
                                "Provider-neutral; no platform API is assumed."
                            ],
                        }
                    ],
                    "thumbnail_key_art_guidance": [
                        "Use approved key art if creator wants a thumbnail."
                    ],
                    "accessibility_caption_notes": [
                        "Review captions before manual posting."
                    ],
                    "provenance_references": [
                        f"storyboard:{STORYBOARD_ID}:v1",
                        f"asset:{ASSET_ID}",
                    ],
                    "governance_boundary": (
                        "Options only; STUDIO//ONE does not publish, schedule, "
                        "upload, or authenticate to external platforms."
                    ),
                    "validation": {
                        "external_publishing_api_called": False,
                        "media_upload_performed": False,
                        "content_published": False,
                    },
                },
            }
        )


class FakeBrainstormRunner:
    def __init__(self, should_raise_secret_error: bool = False) -> None:
        self.calls: list[str] = []
        self.should_raise_secret_error = should_raise_secret_error

    async def __call__(self, *, project_id: str) -> dict[str, Any]:
        self.calls.append(project_id)
        if self.should_raise_secret_error:
            raise ValueError(
                "token=secret-value C:\\Users\\Example\\secret.txt "
                "https://user:pass@example.invalid"
            )
        return {
            "stage": "brainstorm",
            "project_id": project_id,
            "structured_output": {
                "concept_directions": ["Creator-facing option"],
                "governance_boundary": "AI recommendation only.",
            },
            "validation": {
                "agent_memory_retrieval_path": "official_mcp_clickhouse",
                "gemini_can_advance_stage": False,
            },
        }


class FakeMemoryRetriever:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, *, project_id: str) -> dict[str, Any]:
        self.calls.append(project_id)
        return {
            "retrieval": {"mcp_tool_invoked": "run_query"},
            "production_memory": {
                "project": {
                    "project_id": project_id,
                    "title": "Creator Project",
                    "status": "active_in_development",
                    "initial_creative_intent": "Creator intent.",
                    "production_constraints": "Creator constraints.",
                    "source_reference": "creator_project_creation_request",
                },
                "latest_approved_storyboard": {
                    "storyboard_id": STORYBOARD_ID,
                    "storyboard_version": 1,
                    "status": "approved",
                    "approval_status": "approved",
                    "authority_level": "approved_production_state",
                    "source_reference": "storyboard-review",
                    "approved_decision_id": "decision-1",
                    "approved_review_id": REVIEW_ID,
                },
                "approved_assets": [
                    {
                        "asset_id": ASSET_ID,
                        "source_reference": "external_asset_candidate",
                        "external_asset_reference": "creator-submitted://asset",
                    }
                ],
                "assets_count": 1,
                "unresolved_qc_issues": [],
                "decision_log_entries": [
                    {
                        "decision_id": "decision-1",
                        "decision": "approved",
                        "affected_table": "storyboards",
                    }
                ],
            },
        }


def build_client(
    *,
    brainstorm_runner: FakeBrainstormRunner | None = None,
) -> tuple[TestClient, FakeProjectWriter, FakeMemoryRetriever, StudioOneWebDependencies]:
    writer = FakeProjectWriter()
    runner = brainstorm_runner or FakeBrainstormRunner()

    async def refine_runner(**kwargs: Any) -> dict[str, Any]:
        return {
            "stage": "refine",
            "project_id": kwargs["project_id"],
            "structured_output": {
                "creator_selected_or_steered_direction": kwargs["creator_direction"],
            },
            "validation": {"agent_memory_retrieval_path": "official_mcp_clickhouse"},
        }

    async def storyboard_runner(**kwargs: Any) -> dict[str, Any]:
        return {
            "stage": "finalize_storyboard",
            "project_id": kwargs["project_id"],
            "structured_output": {
                "project_id": kwargs["project_id"],
                "working_title": "Creator Project",
                "target_total_runtime": kwargs.get("target_total_runtime") or "",
                "approval_governance_status": "pending_human_review",
                "panels": [{"panel_shot_number": 1, "story_purpose": "Open."}],
            },
            "runtime": {"clickhouse_writes_performed": False},
        }

    project_service = ProjectService(
        project_writer=writer,
        brainstorm_runner=runner,
        refine_runner=refine_runner,
        storyboard_runner=storyboard_runner,
    )
    memory = FakeMemoryRetriever()
    deps = StudioOneWebDependencies(
        project_service=project_service,
        storyboard_service=FakeStoryboardService(),
        generate_assets_service=FakeGenerateAssetsService(),
        external_asset_intake_service=FakeExternalAssetIntakeService(),
        quality_control_service=FakeQualityControlService(),
        post_production_service=FakePostProductionService(),
        publish_service=FakePublishService(),
        brainstorm_runner=runner,
        production_memory_retriever=memory,
    )
    return TestClient(create_app(deps)), writer, memory, deps


def test_project_creation_route_uses_service_and_enters_brainstorm() -> None:
    client, writer, _, _ = build_client()

    response = client.post(
        "/api/projects",
        json={
            "title": "Creator Project",
            "initial_creative_intent": "Create a focused production.",
            "production_constraints": "Use approved material only.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["project_id"] == PROJECT_ID
    assert payload["stage"] == "brainstorm"
    assert payload["brainstorm"]["validation"]["agent_memory_retrieval_path"] == (
        "official_mcp_clickhouse"
    )
    assert len(writer.records) == 1


def test_brainstorm_refine_and_storyboard_routes_delegate_to_backend() -> None:
    client, _, _, _ = build_client()

    brainstorm = client.post(f"/api/projects/{PROJECT_ID}/brainstorm", json={})
    assert brainstorm.status_code == 200
    assert brainstorm.json()["stage"] == "brainstorm"

    bad_refine = client.post(
        f"/api/projects/{PROJECT_ID}/refine",
        json={"creator_direction": " "},
    )
    assert bad_refine.status_code == 400
    assert bad_refine.json()["error"]["type"] == "invalid_creator_action"

    refine = client.post(
        f"/api/projects/{PROJECT_ID}/refine",
        json={"creator_direction": "Use the quieter option."},
    )
    assert refine.status_code == 200
    assert refine.json()["stage"] == "refine"

    storyboard = client.post(
        f"/api/projects/{PROJECT_ID}/storyboard",
        json={
            "creator_action": "Prepare a storyboard candidate.",
            "target_total_runtime": "30 seconds",
        },
    )
    assert storyboard.status_code == 200
    assert storyboard.json()["stage"] == "finalize_storyboard"
    assert storyboard.json()["storyboard_candidate"]["structured_output"]["panels"]


def test_storyboard_review_decision_preserves_human_governance() -> None:
    client, _, _, deps = build_client()
    candidate = {"structured_output": {"project_id": PROJECT_ID, "panels": []}}

    review = client.post(
        "/api/storyboard/reviews",
        json={"project_id": PROJECT_ID, "storyboard_candidate": candidate},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "pending"
    assert review.json()["review_type"] == "storyboard_candidate"

    decision = client.post(
        "/api/storyboard/decisions",
        json={
            "project_id": PROJECT_ID,
            "review_id": REVIEW_ID,
            "action": "approve",
            "decided_by": "creator",
            "decision_reason": "Explicit creator approval.",
            "reviewer_identity_source": "manual",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["decision"] == "approved"
    assert decision.json()["storyboard_created"] is True
    assert deps.storyboard_service.decisions[0]["decided_by"] == "creator"


def test_generate_assets_returns_instructions_not_generated_media_claims() -> None:
    client, _, _, _ = build_client()

    response = client.post(f"/api/projects/{PROJECT_ID}/generate-assets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "generate_assets"
    assert payload["package"]["package_status"] == "instructions_for_creator"
    assert "generated_assets" not in payload["package"]
    assert "approved_assets" not in payload["package"]


def test_external_asset_intake_creates_candidate_not_approved_asset() -> None:
    client, _, _, _ = build_client()

    response = client.post(
        "/api/external-assets",
        json={
            "project_id": PROJECT_ID,
            "approved_storyboard_id": STORYBOARD_ID,
            "approved_storyboard_version": 1,
            "storyboard_panel_shot_reference": "panel 1",
            "asset_type": "image",
            "external_asset_reference": "creator-submitted://asset",
            "submitted_by": "creator",
        },
    )

    assert response.status_code == 200
    candidate = response.json()["candidate"]
    assert candidate["external_asset_candidate_id"] == CANDIDATE_ID
    assert candidate["intake_status"] == "submitted_for_qc"
    assert candidate["qc_status"] == "pending_qc"
    assert candidate["authority_level"] == "external_asset_candidate"
    assert "asset_id" not in candidate


def test_quality_control_recommendation_and_approval_use_review_path() -> None:
    client, _, _, _ = build_client()

    review = client.post(
        f"/api/projects/{PROJECT_ID}/quality-control",
        json={"external_asset_candidate_id": CANDIDATE_ID},
    )
    assert review.status_code == 200
    payload = review.json()
    assert payload["review"]["status"] == "pending"
    assert payload["assessment"]["structured_output"]["recommendation"] == (
        "recommend_approve"
    )

    decision = client.post(
        "/api/quality-control/decisions",
        json={
            "project_id": PROJECT_ID,
            "review_id": QC_REVIEW_ID,
            "action": "approve",
            "decided_by": "creator",
            "decision_reason": "Explicit creator QC approval.",
            "reviewer_identity_source": "manual",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["asset_created"] is True
    assert decision.json()["asset_id"] == ASSET_ID


def test_post_production_route_does_not_claim_editing_completion() -> None:
    client, _, _, _ = build_client()

    response = client.post(f"/api/projects/{PROJECT_ID}/post-production")

    assert response.status_code == 200
    package = response.json()["package"]
    assert package["final_media_edited"] is False
    assert "manual editing instructions" in package["governance_boundary"].lower()
    assert "published" not in str(response.json()).lower()


def test_publish_route_returns_manual_provider_neutral_package() -> None:
    client, _, _, deps = build_client()

    response = client.post(
        f"/api/projects/{PROJECT_ID}/publish",
        json={
            "final_edit_reference": "creator-final-edit://export-v1",
            "final_edit_is_complete": True,
            "requested_platforms": ["short-form social", "long-form video"],
            "required_metadata": {},
        },
    )

    assert response.status_code == 200
    package = response.json()["package"]
    assert package["publishing_readiness"]["readiness_status"] == (
        "ready_for_publish_package"
    )
    assert package["title_options"]
    assert package["seo_keyword_options"]
    assert package["caption_options"]
    assert package["description_options"]
    assert package["hashtag_options"]
    assert package["platform_copy_options"]
    assert package["platform_copy_options"][0]["platform_variant"] == (
        "short-form social"
    )
    serialized = str(package).lower()
    assert "uploaded" not in serialized
    assert "scheduled" not in serialized
    assert " posted" not in serialized
    assert package["validation"]["external_publishing_api_called"] is False
    assert package["validation"]["media_upload_performed"] is False
    assert package["validation"]["content_published"] is False
    assert deps.publish_service.calls[0]["project_id"] == PROJECT_ID


def test_publish_missing_final_edit_context_returns_not_ready_result() -> None:
    client, _, _, _ = build_client()

    response = client.post(
        f"/api/projects/{PROJECT_ID}/publish",
        json={"final_edit_is_complete": False},
    )

    assert response.status_code == 200
    assert response.json()["package"]["publishing_readiness"]["readiness_status"] == (
        "not_ready_missing_final_edit_context"
    )


def test_production_memory_summary_uses_mcp_retriever_boundary() -> None:
    client, _, memory, _ = build_client()

    response = client.get(f"/api/projects/{PROJECT_ID}/memory")

    assert response.status_code == 200
    payload = response.json()
    assert memory.calls == [PROJECT_ID]
    assert payload["retrieval"]["path"] == "official_mcp_clickhouse"
    assert payload["retrieval"]["mcp_tool_invoked"] == "run_query"
    assert payload["retrieval"]["clickhouse_writes_performed"] is False
    assert payload["approved_storyboard"]["present"] is True
    assert payload["provenance_references"]


def test_workflow_contract_exposes_exactly_seven_canonical_stages() -> None:
    client, _, _, _ = build_client()

    response = client.get("/api/workflow")

    assert response.status_code == 200
    payload = response.json()
    assert tuple(payload["stages"]) == CANONICAL_STAGE_IDENTIFIERS
    assert payload["stage_labels"] == [
        "BRAINSTORM",
        "REFINE",
        "FINALIZE STORYBOARD",
        "GENERATE ASSETS",
        "QUALITY CONTROL",
        "POST PRODUCTION",
        "PUBLISH",
    ]
    assert len(payload["stage_labels"]) == 7


def test_rendered_html_and_errors_do_not_expose_secret_material() -> None:
    runner = FakeBrainstormRunner(should_raise_secret_error=True)
    client, _, _, _ = build_client(brainstorm_runner=runner)

    html = client.get("/").text
    assert "CLICKHOUSE_HOST" not in html
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in html
    assert "C:\\Users" not in html

    response = client.post(f"/api/projects/{PROJECT_ID}/brainstorm", json={})
    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "secret-value" not in message
    assert "C:\\Users\\Example" not in message
    assert "user:pass" not in message
    assert "<redacted>" in message


def test_frontend_static_assets_are_provider_neutral_and_not_direct_clickhouse() -> None:
    root = Path("studio_one/web")
    script = (root / "static" / "app.js").read_text(encoding="utf-8")
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    css = (root / "static" / "app.css").read_text(encoding="utf-8")

    assert "/api/" in script
    assert "clickhouse" not in script.lower()
    assert "fetch(\"http" not in script
    assert "fetch('http" not in script
    assert "api_key" not in script.lower()
    assert "password" not in script.lower()
    assert "C:\\Users" not in script
    assert "C:\\Users" not in html
    assert "letter-spacing: 0" in css
    for label in [
        "BRAINSTORM",
        "REFINE",
        "FINALIZE STORYBOARD",
        "GENERATE ASSETS",
        "QUALITY CONTROL",
        "POST PRODUCTION",
        "PUBLISH",
    ]:
        assert label in script or label in html


def test_no_non_google_ai_runtime_integration_is_introduced() -> None:
    web_source = Path("studio_one/web/app.py").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "google-adk" in requirements
    assert "google-genai" in requirements
    assert "openai" not in requirements
    assert "anthropic" not in requirements
    assert "elevenlabs" not in requirements
    assert "openai." not in web_source
    assert "anthropic" not in web_source.lower()


def load_tests(
    _loader: unittest.TestLoader,
    _tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite
