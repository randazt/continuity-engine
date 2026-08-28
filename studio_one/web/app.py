"""Judge-facing FastAPI application for STUDIO//ONE."""

from __future__ import annotations

import re
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic import Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from studio_one.agents.refinement_agent import (
    ApprovedStoryboardRequiredError,
    PostProductionContextRequiredError,
    PublishContextRequiredError,
    QualityControlContextRequiredError,
    run_brainstorm_agent,
)
from studio_one.integrations.clickhouse_mcp import retrieve_publish_memory_bundle
from studio_one.services.asset_intake_service import (
    ExternalAssetIntakeRequest,
    ExternalAssetIntakeService,
    build_external_asset_intake_service,
)
from studio_one.services.generate_assets_service import (
    GenerateAssetsRequest,
    GenerateAssetsService,
    build_generate_assets_service,
)
from studio_one.services.post_production_service import (
    PostProductionRequest,
    PostProductionService,
    build_post_production_service,
)
from studio_one.services.project_service import (
    CreateProjectRequest,
    FinalizeStoryboardRequest,
    ProjectService,
    RefineProjectRequest,
    build_project_service,
)
from studio_one.services.publish_service import (
    PublishRequest,
    PublishService,
    build_publish_service,
)
from studio_one.services.quality_control_service import (
    QualityControlDecisionRequest,
    QualityControlRequest,
    QualityControlService,
    build_quality_control_service,
)
from studio_one.services.storyboard_service import (
    DecideStoryboardReviewRequest,
    StoryboardService,
    SubmitStoryboardCandidateReviewRequest,
    build_storyboard_service,
)
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS


WEB_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = WEB_ROOT / "static"
INDEX_HTML = WEB_ROOT / "templates" / "index.html"

MemoryRetriever = Callable[..., Awaitable[dict[str, Any]]]
BrainstormRunner = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class StudioOneWebDependencies:
    project_service: ProjectService
    storyboard_service: StoryboardService
    generate_assets_service: GenerateAssetsService
    external_asset_intake_service: ExternalAssetIntakeService
    quality_control_service: QualityControlService
    post_production_service: PostProductionService
    publish_service: PublishService
    brainstorm_runner: BrainstormRunner
    production_memory_retriever: MemoryRetriever


class RefineBody(BaseModel):
    creator_direction: str = Field(min_length=1)


class StoryboardBody(BaseModel):
    creator_action: str = Field(min_length=1)
    target_total_runtime: str = ""


class BrainstormBody(BaseModel):
    pass


class QualityControlBody(BaseModel):
    external_asset_candidate_id: str = Field(min_length=1)


class PublishBody(BaseModel):
    final_edit_reference: str | None = None
    final_edit_is_complete: bool = False
    final_edit_notes: str = ""
    required_metadata: dict[str, Any] = Field(default_factory=dict)
    requested_platforms: list[str] = Field(default_factory=list)
    post_production_package: dict[str, Any] | None = None


def build_web_dependencies() -> StudioOneWebDependencies:
    return StudioOneWebDependencies(
        project_service=build_project_service(),
        storyboard_service=build_storyboard_service(),
        generate_assets_service=build_generate_assets_service(),
        external_asset_intake_service=build_external_asset_intake_service(),
        quality_control_service=build_quality_control_service(),
        post_production_service=build_post_production_service(),
        publish_service=build_publish_service(),
        brainstorm_runner=run_brainstorm_agent,
        production_memory_retriever=retrieve_publish_memory_bundle,
    )


def create_app(
    dependencies: StudioOneWebDependencies | None = None,
) -> FastAPI:
    app = FastAPI(
        title="STUDIO//ONE",
        description="Human-governed production intelligence for creators.",
        version="0.1.0",
    )
    app.state.studio_one_dependencies = dependencies
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return _safe_error_response(
            "invalid_request",
            "Request validation failed. Check required creator input fields.",
            422,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return _safe_error_response(
            "invalid_creator_action",
            _safe_message(str(exc), fallback="Invalid creator action."),
            400,
        )

    async def workflow_gate_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return _safe_error_response(
            "workflow_gate_not_ready",
            _safe_message(str(exc), fallback="Workflow gate is not ready."),
            409,
        )

    for exception_type in (
        ApprovedStoryboardRequiredError,
        QualityControlContextRequiredError,
        PostProductionContextRequiredError,
        PublishContextRequiredError,
    ):
        app.add_exception_handler(exception_type, workflow_gate_handler)

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(
        _request: Request,
        exc: RuntimeError,
    ) -> JSONResponse:
        message = str(exc)
        if "No rows returned for project" in message:
            return _safe_error_response(
                "project_not_found",
                "Project was not found in production memory.",
                404,
            )
        return _safe_error_response(
            "runtime_unavailable",
            "STUDIO//ONE runtime is unavailable. Check MCP, Gemini, and configuration.",
            502,
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        _request: Request,
        _exc: Exception,
    ) -> JSONResponse:
        return _safe_error_response(
            "runtime_unavailable",
            "STUDIO//ONE runtime is unavailable. Check MCP, Gemini, and configuration.",
            502,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return await http_exception_handler(request, exc)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))

    @app.get("/api/workflow")
    async def workflow() -> dict[str, Any]:
        return {
            "product": "STUDIO//ONE",
            "thesis": "The studio remembers. The agent reasons. You direct.",
            "runtime_boundary": (
                "Creator -> FastAPI/UI -> STUDIO//ONE services -> "
                "Google ADK/Gemini -> official mcp-clickhouse -> "
                "ClickHouse production memory"
            ),
            "stages": list(CANONICAL_STAGE_IDENTIFIERS),
            "stage_labels": [
                "BRAINSTORM",
                "REFINE",
                "FINALIZE STORYBOARD",
                "GENERATE ASSETS",
                "QUALITY CONTROL",
                "POST PRODUCTION",
                "PUBLISH",
            ],
            "authority_states": [
                "AI Recommendation",
                "Pending Human Review",
                "Creator Approved",
                "Approved Production State",
                "External Asset Candidate",
                "QC Recommendation",
                "Needs Revision",
                "Rejected",
            ],
            "does": [
                "brainstorm with the creator",
                "refine creative ideas",
                "retrieve production memory through official mcp-clickhouse",
                "create storyboard candidates",
                "support human storyboard approval",
                "prepare asset requirements and prompt packages",
                "audit/reuse existing approved assets before new creation",
                "accept creator-supplied external assets for QC",
                "perform Gemini-assisted quality control",
                "route consequential decisions to the creator",
                "prepare post-production editing packages",
                "prepare publishing packages",
                "preserve provenance, production memory, and human decisions",
            ],
            "does_not": [
                "generate images itself",
                "generate video itself",
                "synthesize TTS/audio itself",
                "choose external generation tools for the creator",
                "perform final video editing",
                "operate external editing software",
                "publish directly to social/video platforms",
                "authenticate to publishing platforms",
                "automatically establish canon",
                "automatically approve consequential creative decisions",
            ],
        }

    @post_json(app, "/api/projects")
    async def create_project(
        request: Request,
        payload: CreateProjectRequest,
    ) -> dict[str, Any]:
        result = await _dependencies(request).project_service.create_project_and_start_brainstorm(
            payload
        )
        return result.model_dump()

    @post_json(app, "/api/projects/{project_id}/brainstorm")
    async def brainstorm(
        request: Request,
        project_id: str,
        _payload: BrainstormBody,
    ) -> dict[str, Any]:
        return await _dependencies(request).brainstorm_runner(project_id=project_id)

    @post_json(app, "/api/projects/{project_id}/refine")
    async def refine(
        request: Request,
        project_id: str,
        payload: RefineBody,
    ) -> dict[str, Any]:
        result = await _dependencies(request).project_service.refine_project(
            RefineProjectRequest(
                project_id=project_id,
                creator_direction=payload.creator_direction,
            )
        )
        return result.model_dump()

    @post_json(app, "/api/projects/{project_id}/storyboard")
    async def storyboard(
        request: Request,
        project_id: str,
        payload: StoryboardBody,
    ) -> dict[str, Any]:
        result = await _dependencies(
            request
        ).project_service.finalize_storyboard_candidate(
            FinalizeStoryboardRequest(
                project_id=project_id,
                creator_action=payload.creator_action,
                target_total_runtime=payload.target_total_runtime,
            )
        )
        return result.model_dump()

    @post_json(app, "/api/storyboard/reviews")
    async def submit_storyboard_review(
        request: Request,
        payload: SubmitStoryboardCandidateReviewRequest,
    ) -> dict[str, Any]:
        result = _dependencies(request).storyboard_service.submit_candidate_for_review(
            payload
        )
        return asdict(result)

    @post_json(app, "/api/storyboard/decisions")
    async def decide_storyboard_review(
        request: Request,
        payload: DecideStoryboardReviewRequest,
    ) -> dict[str, Any]:
        result = _dependencies(request).storyboard_service.decide_review(payload)
        return asdict(result)

    @post_json(app, "/api/projects/{project_id}/generate-assets")
    async def generate_assets(
        request: Request,
        project_id: str,
    ) -> dict[str, Any]:
        result = await _dependencies(
            request
        ).generate_assets_service.generate_assets_package(
            GenerateAssetsRequest(project_id=project_id)
        )
        return result.model_dump()

    @post_json(app, "/api/external-assets")
    async def external_asset_intake(
        request: Request,
        payload: ExternalAssetIntakeRequest,
    ) -> dict[str, Any]:
        result = _dependencies(
            request
        ).external_asset_intake_service.submit_candidate_for_qc(payload)
        return result.model_dump()

    @post_json(app, "/api/projects/{project_id}/quality-control")
    async def quality_control(
        request: Request,
        project_id: str,
        payload: QualityControlBody,
    ) -> dict[str, Any]:
        result = await _dependencies(request).quality_control_service.run_quality_control(
            QualityControlRequest(
                project_id=project_id,
                external_asset_candidate_id=payload.external_asset_candidate_id,
            )
        )
        return result.model_dump()

    @post_json(app, "/api/quality-control/decisions")
    async def decide_quality_control(
        request: Request,
        payload: QualityControlDecisionRequest,
    ) -> dict[str, Any]:
        return _dependencies(
            request
        ).quality_control_service.decide_quality_control_review(payload)

    @post_json(app, "/api/projects/{project_id}/post-production")
    async def post_production(
        request: Request,
        project_id: str,
    ) -> dict[str, Any]:
        result = await _dependencies(
            request
        ).post_production_service.prepare_editing_package(
            PostProductionRequest(project_id=project_id)
        )
        return result.model_dump()

    @post_json(app, "/api/projects/{project_id}/publish")
    async def publish(
        request: Request,
        project_id: str,
        payload: PublishBody,
    ) -> dict[str, Any]:
        result = await _dependencies(request).publish_service.prepare_publish_package(
            PublishRequest(
                project_id=project_id,
                final_edit_reference=payload.final_edit_reference,
                final_edit_is_complete=payload.final_edit_is_complete,
                final_edit_notes=payload.final_edit_notes,
                required_metadata=payload.required_metadata,
                requested_platforms=payload.requested_platforms,
                post_production_package=payload.post_production_package,
            )
        )
        return result.model_dump()

    @app.get("/api/projects/{project_id}/memory")
    async def production_memory(
        request: Request,
        project_id: str,
    ) -> dict[str, Any]:
        bundle = await _dependencies(request).production_memory_retriever(
            project_id=project_id
        )
        return summarize_production_memory(bundle)

    return app


def post_json(app: FastAPI, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    return app.post(path, response_class=JSONResponse)


def _dependencies(request: Request) -> StudioOneWebDependencies:
    dependencies = request.app.state.studio_one_dependencies
    if dependencies is None:
        dependencies = build_web_dependencies()
        request.app.state.studio_one_dependencies = dependencies
    return dependencies


def summarize_production_memory(bundle: dict[str, Any]) -> dict[str, Any]:
    memory = bundle.get("production_memory") or {}
    project = memory.get("project") or {}
    storyboard = (
        memory.get("latest_approved_storyboard")
        or memory.get("approved_storyboard")
        or {}
    )
    approved_assets = memory.get("approved_assets") or memory.get("assets") or []
    unresolved_qc = memory.get("unresolved_qc_issues") or []
    decisions = memory.get("decision_log_entries") or []
    latest_review = memory.get("review_queue")

    return {
        "retrieval": {
            "path": "official_mcp_clickhouse",
            "mcp_tool_invoked": (bundle.get("retrieval") or {}).get(
                "mcp_tool_invoked"
            ),
            "clickhouse_writes_performed": False,
        },
        "project": {
            "project_id": project.get("project_id", ""),
            "title": project.get("title", ""),
            "status": project.get("status", ""),
            "creator_intent": _safe_message(
                str(project.get("initial_creative_intent") or ""),
                fallback="",
            ),
            "production_constraints": _safe_message(
                str(project.get("production_constraints") or ""),
                fallback="",
            ),
        },
        "approved_storyboard": {
            "present": bool(storyboard),
            "storyboard_id": storyboard.get("storyboard_id", ""),
            "version": int(storyboard.get("storyboard_version") or 0),
            "status": storyboard.get("status", ""),
            "approval_status": storyboard.get("approval_status", ""),
            "authority_level": storyboard.get("authority_level", ""),
        },
        "approved_assets_count": len(approved_assets),
        "assets_count": int(memory.get("assets_count") or len(approved_assets)),
        "pending_reviews": _pending_review_summary(latest_review, unresolved_qc),
        "human_decisions": [
            {
                "decision_id": decision.get("decision_id", ""),
                "decision": decision.get("decision", ""),
                "affected_table": decision.get("affected_table", ""),
            }
            for decision in decisions[:10]
            if isinstance(decision, dict)
        ],
        "provenance_references": _provenance_references(memory),
    }


def _pending_review_summary(
    latest_review: dict[str, Any] | None,
    unresolved_qc: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    if latest_review and latest_review.get("status") in {
        "pending",
        "qc_review_pending_human_decision",
    }:
        pending.append(
            {
                "type": latest_review.get("review_type", "review"),
                "status": latest_review.get("status", "pending"),
            }
        )
    for issue in unresolved_qc[:10]:
        pending.append(
            {
                "type": "asset_qc",
                "status": issue.get("qc_status", ""),
                "storyboard_reference": issue.get(
                    "storyboard_panel_shot_reference",
                    "",
                ),
            }
        )
    return pending


def _provenance_references(memory: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    project = memory.get("project") or {}
    storyboard = (
        memory.get("latest_approved_storyboard")
        or memory.get("approved_storyboard")
        or {}
    )
    for value in (
        project.get("source_reference"),
        storyboard.get("source_reference"),
        storyboard.get("approved_decision_id"),
        storyboard.get("approved_review_id"),
    ):
        _append_reference(refs, value)
    for asset in (memory.get("approved_assets") or memory.get("assets") or [])[:20]:
        if isinstance(asset, dict):
            _append_reference(refs, asset.get("asset_id"))
            _append_reference(refs, asset.get("source_reference"))
            _append_reference(refs, asset.get("external_asset_reference"))
    for decision in (memory.get("decision_log_entries") or [])[:10]:
        if isinstance(decision, dict):
            _append_reference(refs, decision.get("decision_id"))
    return refs[:30]


def _append_reference(refs: list[str], value: Any) -> None:
    text = _safe_message(str(value or "").strip(), fallback="")
    if text and text not in refs:
        refs.append(text)


def _safe_error_response(
    error_type: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": error_type, "message": message}},
    )


def _safe_message(value: str, fallback: str) -> str:
    text = value.strip()
    if not text:
        return fallback
    text = re.sub(
        r"https://([^/\s:@]+):([^/\s@]+)@",
        "https://<redacted>:<redacted>@",
        text,
    )
    text = re.sub(
        r"projects/[^/\s]+/secrets/[^/\s]+/versions/[^/\s]+",
        "projects/<redacted>/secrets/<redacted>/versions/<redacted>",
        text,
    )
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "<local-user-path>", text)
    text = re.sub(r"(?i)(password|token|api[_-]?key|secret)=\S+", r"\1=<redacted>", text)
    return text[:500] or fallback


app = create_app()
