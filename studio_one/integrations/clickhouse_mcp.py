"""Read-only ClickHouse production-memory retrieval through official MCP."""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from typing import Any
from uuid import UUID

import anyio
from google.cloud import secretmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from studio_one.config import StudioOneConfig
from studio_one.config import mcp_python_executable
from studio_one.config import repo_root


_DEFAULT_CONFIG = StudioOneConfig.from_env()
GOOGLE_CLOUD_PROJECT = _DEFAULT_CONFIG.google_cloud_project
CLICKHOUSE_DATABASE = _DEFAULT_CONFIG.clickhouse_database


def _uuid_literal(value: str, field_name: str) -> str:
    try:
        parsed = UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc
    return f"toUUID('{parsed}')"


def get_clickhouse_password(config: StudioOneConfig | None = None) -> str:
    """Retrieve the ClickHouse password from Google Secret Manager."""
    runtime_config = config or StudioOneConfig.from_env()
    client = secretmanager.SecretManagerServiceClient()
    name = (
        f"projects/{runtime_config.google_cloud_project}/secrets/"
        f"{runtime_config.clickhouse_password_secret}/versions/latest"
    )
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def _parse_mcp_tool_json(call_result: Any, secret_value: str) -> dict[str, Any]:
    if getattr(call_result, "isError", False):
        raise RuntimeError(str(call_result).replace(secret_value, "<redacted>"))

    for item in getattr(call_result, "content", []) or []:
        if getattr(item, "type", None) == "text" and getattr(item, "text", None):
            return json.loads(item.text)

    structured = getattr(call_result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    raise RuntimeError(str(call_result).replace(secret_value, "<redacted>"))


def _required_single_row(payload: dict[str, Any], label: str) -> dict[str, Any]:
    rows = payload.get("rows", [])
    if not rows:
        raise RuntimeError(f"No rows returned for {label}")
    return dict(zip(payload.get("columns", []), rows[0]))


def _optional_single_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    rows = payload.get("rows", [])
    if not rows:
        return None
    return dict(zip(payload.get("columns", []), rows[0]))


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    columns = payload.get("columns", [])
    return [dict(zip(columns, row)) for row in payload.get("rows", [])]


async def _run_query(
    session: ClientSession,
    query: str,
    secret_value: str,
) -> dict[str, Any]:
    result = await session.call_tool("run_query", {"query": query})
    return _parse_mcp_tool_json(result, secret_value)


def _project_query(project_id: str, database: str) -> str:
    return f"""
SELECT
  toString(project_id) AS project_id,
  title,
  status,
  current_canon_version,
  authority_level,
  authoritative_source,
  source_reference,
  source_version,
  approval_status,
  state_version,
  toString(approved_decision_id) AS approved_decision_id,
  production_constraints,
  initial_creative_intent
FROM `{database}`.`projects`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
LIMIT 1
""".strip()


def _review_query(project_id: str, review_id: str | None, database: str) -> str:
    where = [f"project_id = {_uuid_literal(project_id, 'project_id')}"]
    if review_id:
        where.append(f"review_id = {_uuid_literal(review_id, 'review_id')}")

    return f"""
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
  toString(created_at) AS created_at,
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
  recommendation_version,
  toString(supersedes_review_id) AS supersedes_review_id
FROM `{database}`.`review_queue`
WHERE {" AND ".join(where)}
ORDER BY created_at DESC, review_id
LIMIT 1
""".strip()


def _decision_query(
    project_id: str,
    review_id: str | None,
    decision_id: str | None,
    database: str,
) -> str:
    where = [f"project_id = {_uuid_literal(project_id, 'project_id')}"]
    if review_id:
        where.append(f"review_id = {_uuid_literal(review_id, 'review_id')}")
    if decision_id:
        where.append(f"decision_id = {_uuid_literal(decision_id, 'decision_id')}")

    return f"""
SELECT
  toString(decision_id) AS decision_id,
  toString(project_id) AS project_id,
  toString(review_id) AS review_id,
  toString(asset_id) AS asset_id,
  decision,
  decided_by,
  decision_reason,
  previous_state,
  resulting_state,
  agent_recommendation,
  agent_confidence,
  source_reference,
  toString(decided_at) AS decided_at,
  authority_level,
  reviewer_identity_source,
  affected_table,
  affected_state_version,
  resulting_state_version
FROM `{database}`.`decision_log`
WHERE {" AND ".join(where)}
ORDER BY decided_at DESC, decision_id
LIMIT 1
""".strip()


def _assets_count_query(project_id: str, database: str) -> str:
    return f"""
SELECT count() AS assets_count
FROM `{database}`.`assets`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
""".strip()


def _assets_inventory_query(project_id: str, database: str) -> str:
    return f"""
SELECT
  toString(asset_id) AS asset_id,
  toString(project_id) AS project_id,
  asset_type,
  name,
  description,
  continuity_status,
  canon_version,
  source_reference,
  toString(created_at) AS created_at,
  toString(updated_at) AS updated_at,
  authority_level,
  authoritative_source,
  source_version,
  approval_status,
  state_version,
  toString(approved_decision_id) AS approved_decision_id,
  toString(reuse_source_asset_id) AS reuse_source_asset_id,
  reuse_relationship
FROM `{database}`.`assets`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
ORDER BY asset_type, name, asset_id
LIMIT 200
""".strip()


def _latest_approved_storyboard_query(project_id: str, database: str) -> str:
    return f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  toString(project_id) AS project_id,
  storyboard_version,
  status,
  approval_status,
  authority_level,
  title,
  target_total_runtime,
  creative_narrative_objective,
  production_constraints_applied,
  unresolved_issues,
  storyboard_json,
  storyboard_schema_version,
  source_reference,
  source_version,
  authoritative_source,
  toString(approved_decision_id) AS approved_decision_id,
  toString(approved_review_id) AS approved_review_id,
  approved_by,
  reviewer_identity_source,
  toString(approved_at) AS approved_at,
  toString(created_at) AS created_at,
  toString(supersedes_storyboard_id) AS supersedes_storyboard_id
FROM `{database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
ORDER BY storyboard_version DESC, approved_at DESC, storyboard_id DESC
LIMIT 1
""".strip()


def _approved_storyboard_query(
    project_id: str,
    approved_storyboard_id: str,
    approved_storyboard_version: int,
    database: str,
) -> str:
    if int(approved_storyboard_version) < 1:
        raise ValueError("approved_storyboard_version must be a positive integer")
    return f"""
SELECT
  toString(storyboard_id) AS storyboard_id,
  toString(project_id) AS project_id,
  storyboard_version,
  status,
  approval_status,
  authority_level,
  title,
  target_total_runtime,
  creative_narrative_objective,
  production_constraints_applied,
  unresolved_issues,
  storyboard_json,
  storyboard_schema_version,
  source_reference,
  source_version,
  authoritative_source,
  toString(approved_decision_id) AS approved_decision_id,
  toString(approved_review_id) AS approved_review_id,
  approved_by,
  reviewer_identity_source,
  toString(approved_at) AS approved_at,
  toString(created_at) AS created_at,
  toString(supersedes_storyboard_id) AS supersedes_storyboard_id
FROM `{database}`.`storyboards`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND storyboard_id = {_uuid_literal(approved_storyboard_id, "approved_storyboard_id")}
  AND storyboard_version = {int(approved_storyboard_version)}
  AND status = 'approved'
  AND approval_status = 'approved'
  AND authority_level = 'approved_production_state'
LIMIT 1
""".strip()


def _generation_package_query(
    project_id: str,
    generation_package_id: str,
    package_version: int,
    database: str,
) -> str:
    if int(package_version) < 1:
        raise ValueError("package_version must be a positive integer")
    return f"""
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
  package_schema_version,
  source_reference,
  source_version,
  evidence_references,
  gemini_model,
  gemini_response_id,
  gemini_prompt_version,
  created_by,
  toString(created_at) AS created_at,
  toString(supersedes_generation_package_id) AS supersedes_generation_package_id
FROM `{database}`.`generation_packages`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND generation_package_id = {_uuid_literal(generation_package_id, "generation_package_id")}
  AND package_version = {int(package_version)}
  AND status = 'instructions_for_creator'
  AND authority_level = 'production_instruction'
LIMIT 1
""".strip()


def _external_asset_candidate_query(
    project_id: str,
    external_asset_candidate_id: str,
    database: str,
) -> str:
    return f"""
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
FROM `{database}`.`external_asset_intake`
WHERE project_id = {_uuid_literal(project_id, "project_id")}
  AND external_asset_candidate_id = {_uuid_literal(external_asset_candidate_id, "external_asset_candidate_id")}
  AND intake_status = 'submitted_for_qc'
  AND qc_status = 'pending_qc'
  AND authority_level = 'external_asset_candidate'
LIMIT 1
""".strip()


def _storyboard_reference_number(storyboard_reference: str) -> int | None:
    match = re.search(r"\d+", storyboard_reference)
    if not match:
        return None
    return int(match.group(0))


def _relevant_storyboard_panel(
    storyboard: dict[str, Any] | None,
    storyboard_reference: str,
) -> dict[str, Any] | None:
    if not storyboard:
        return None
    raw_storyboard = storyboard.get("storyboard_json") or ""
    try:
        storyboard_payload = json.loads(raw_storyboard)
    except json.JSONDecodeError:
        return None
    panels = storyboard_payload.get("panels") or []
    if not isinstance(panels, list):
        return None

    reference_number = _storyboard_reference_number(storyboard_reference)
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        if (
            reference_number is not None
            and panel.get("panel_shot_number") == reference_number
        ):
            return panel
        panel_reference = str(
            panel.get("storyboard_reference")
            or panel.get("panel_reference")
            or panel.get("shot_reference")
            or ""
        )
        if panel_reference and panel_reference == storyboard_reference:
            return panel
    return None


def _nullable_uuid_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def retrieve_project_memory_bundle(
    project_id: str,
    review_id: str | None = None,
    decision_id: str | None = None,
    generation_package_id: str | None = None,
    generation_package_version: int | None = None,
    external_asset_candidate_id: str | None = None,
    config: StudioOneConfig | None = None,
) -> dict[str, Any]:
    """Retrieve project production memory through official mcp-clickhouse.

    Retrieval is read-only and project-scoped. Optional review and decision IDs
    narrow the retrieved review or decision context without introducing
    built-in project assumptions.
    """
    runtime_config = config or StudioOneConfig.from_env()
    secret_value = get_clickhouse_password(runtime_config)
    if generation_package_id and generation_package_version is None:
        raise ValueError("generation_package_version is required with generation_package_id")
    if generation_package_version is not None and not generation_package_id:
        raise ValueError("generation_package_id is required with generation_package_version")

    child_env = {
        "CLICKHOUSE_HOST": runtime_config.clickhouse_host,
        "CLICKHOUSE_PORT": str(runtime_config.clickhouse_port),
        "CLICKHOUSE_USER": runtime_config.clickhouse_user,
        "CLICKHOUSE_PASSWORD": secret_value,
        "CLICKHOUSE_DATABASE": runtime_config.clickhouse_database,
        "CLICKHOUSE_SECURE": str(runtime_config.clickhouse_secure).lower(),
        "CLICKHOUSE_VERIFY": str(runtime_config.clickhouse_verify).lower(),
        "CLICKHOUSE_MCP_SERVER_TRANSPORT": "stdio",
        "CLICKHOUSE_ALLOW_WRITE_ACCESS": "false",
        "CLICKHOUSE_ALLOW_DROP": "false",
        "CLICKHOUSE_MCP_QUERY_TIMEOUT": str(
            runtime_config.mcp_query_timeout_seconds
        ),
    }

    params = StdioServerParameters(
        command=str(mcp_python_executable()),
        args=["-m", "mcp_clickhouse.main"],
        env=child_env,
        cwd=str(repo_root()),
    )

    query_purposes = [
        "Retrieve approved project memory by project_id",
        "Retrieve project-scoped review context",
        "Retrieve project-scoped human decision audit context",
        "Retrieve latest approved storyboard production state",
        "Retrieve existing project asset inventory",
        "Read current project asset count",
    ]
    if generation_package_id:
        query_purposes.append("Retrieve exact generation package provenance")
    if external_asset_candidate_id:
        query_purposes.append("Retrieve exact external asset candidate provenance")

    with open(os.devnull, "w", encoding="utf-8") as errlog:
        with anyio.fail_after(120):
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=100),
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    project_payload = await _run_query(
                        session,
                        _project_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    review_payload = await _run_query(
                        session,
                        _review_query(
                            project_id,
                            review_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    decision_payload = await _run_query(
                        session,
                        _decision_query(
                            project_id,
                            review_id,
                            decision_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    storyboard_payload = await _run_query(
                        session,
                        _latest_approved_storyboard_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    assets_inventory_payload = await _run_query(
                        session,
                        _assets_inventory_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    assets_payload = await _run_query(
                        session,
                        _assets_count_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    generation_package_payload = (
                        await _run_query(
                            session,
                            _generation_package_query(
                                project_id,
                                generation_package_id,
                                int(generation_package_version),
                                runtime_config.clickhouse_database,
                            ),
                            secret_value,
                        )
                        if generation_package_id
                        else {"rows": [], "columns": []}
                    )
                    external_asset_candidate_payload = (
                        await _run_query(
                            session,
                            _external_asset_candidate_query(
                                project_id,
                                external_asset_candidate_id,
                                runtime_config.clickhouse_database,
                            ),
                            secret_value,
                        )
                        if external_asset_candidate_id
                        else {"rows": [], "columns": []}
                    )

    return {
        "retrieval": {
            "secret_manager_retrieval_succeeded": True,
            "mcp_server_initialized": True,
            "mcp_tools_discovered": [tool.name for tool in tools.tools],
            "mcp_tool_invoked": "run_query",
            "mcp_query_purposes": query_purposes,
            "clickhouse_writes_performed": False,
        },
        "production_memory": {
            "project": _required_single_row(project_payload, "project"),
            "review_queue": _optional_single_row(review_payload),
            "decision_log": _optional_single_row(decision_payload),
            "latest_approved_storyboard": _optional_single_row(
                storyboard_payload
            ),
            "assets": _rows(assets_inventory_payload),
            "generation_package": _optional_single_row(
                generation_package_payload
            ),
            "external_asset_candidate": _optional_single_row(
                external_asset_candidate_payload
            ),
            "assets_count": int(
                _required_single_row(assets_payload, "assets count")["assets_count"]
            ),
        },
    }


async def retrieve_qc_memory_bundle(
    project_id: str,
    external_asset_candidate_id: str,
    config: StudioOneConfig | None = None,
) -> dict[str, Any]:
    """Retrieve exact QUALITY CONTROL context through official mcp-clickhouse."""
    runtime_config = config or StudioOneConfig.from_env()
    secret_value = get_clickhouse_password(runtime_config)

    child_env = {
        "CLICKHOUSE_HOST": runtime_config.clickhouse_host,
        "CLICKHOUSE_PORT": str(runtime_config.clickhouse_port),
        "CLICKHOUSE_USER": runtime_config.clickhouse_user,
        "CLICKHOUSE_PASSWORD": secret_value,
        "CLICKHOUSE_DATABASE": runtime_config.clickhouse_database,
        "CLICKHOUSE_SECURE": str(runtime_config.clickhouse_secure).lower(),
        "CLICKHOUSE_VERIFY": str(runtime_config.clickhouse_verify).lower(),
        "CLICKHOUSE_MCP_SERVER_TRANSPORT": "stdio",
        "CLICKHOUSE_ALLOW_WRITE_ACCESS": "false",
        "CLICKHOUSE_ALLOW_DROP": "false",
        "CLICKHOUSE_MCP_QUERY_TIMEOUT": str(
            runtime_config.mcp_query_timeout_seconds
        ),
    }
    params = StdioServerParameters(
        command=str(mcp_python_executable()),
        args=["-m", "mcp_clickhouse.main"],
        env=child_env,
        cwd=str(repo_root()),
    )

    query_purposes = [
        "Retrieve approved project memory by project_id",
        "Retrieve exact external asset candidate provenance",
        "Retrieve exact approved storyboard production state",
        "Retrieve exact generation package provenance when candidate references one",
        "Retrieve existing project asset inventory for continuity context",
        "Read current project asset count",
    ]

    with open(os.devnull, "w", encoding="utf-8") as errlog:
        with anyio.fail_after(120):
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=100),
                ) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    project_payload = await _run_query(
                        session,
                        _project_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    candidate_payload = await _run_query(
                        session,
                        _external_asset_candidate_query(
                            project_id,
                            external_asset_candidate_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    candidate = _optional_single_row(candidate_payload)
                    storyboard_payload = {"rows": [], "columns": []}
                    generation_package_payload = {"rows": [], "columns": []}
                    if candidate:
                        storyboard_payload = await _run_query(
                            session,
                            _approved_storyboard_query(
                                project_id,
                                candidate["approved_storyboard_id"],
                                int(candidate["approved_storyboard_version"]),
                                runtime_config.clickhouse_database,
                            ),
                            secret_value,
                        )
                        package_id = _nullable_uuid_value(
                            candidate.get("source_generation_package_id")
                        )
                        package_version = int(
                            candidate.get("source_generation_package_version") or 0
                        )
                        if package_id:
                            generation_package_payload = await _run_query(
                                session,
                                _generation_package_query(
                                    project_id,
                                    package_id,
                                    package_version,
                                    runtime_config.clickhouse_database,
                                ),
                                secret_value,
                            )
                    assets_inventory_payload = await _run_query(
                        session,
                        _assets_inventory_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )
                    assets_payload = await _run_query(
                        session,
                        _assets_count_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
                    )

    approved_storyboard = _optional_single_row(storyboard_payload)
    candidate = _optional_single_row(candidate_payload)
    relevant_panel = _relevant_storyboard_panel(
        approved_storyboard,
        candidate.get("storyboard_panel_shot_reference", "") if candidate else "",
    )
    return {
        "retrieval": {
            "secret_manager_retrieval_succeeded": True,
            "mcp_server_initialized": True,
            "mcp_tools_discovered": [tool.name for tool in tools.tools],
            "mcp_tool_invoked": "run_query",
            "mcp_query_purposes": query_purposes,
            "clickhouse_writes_performed": False,
        },
        "production_memory": {
            "project": _required_single_row(project_payload, "project"),
            "approved_storyboard": approved_storyboard,
            "relevant_storyboard_panel": relevant_panel,
            "generation_package": _optional_single_row(
                generation_package_payload
            ),
            "external_asset_candidate": candidate,
            "assets": _rows(assets_inventory_payload),
            "assets_count": int(
                _required_single_row(assets_payload, "assets count")["assets_count"]
            ),
        },
    }
