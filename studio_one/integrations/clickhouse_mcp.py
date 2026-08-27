"""Read-only ClickHouse production-memory retrieval through official MCP."""

from __future__ import annotations

import json
import os
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


async def retrieve_project_memory_bundle(
    project_id: str,
    review_id: str | None = None,
    decision_id: str | None = None,
    config: StudioOneConfig | None = None,
) -> dict[str, Any]:
    """Retrieve project production memory through official mcp-clickhouse.

    Retrieval is read-only and project-scoped. Optional review and decision IDs
    narrow the retrieved review or decision context without introducing
    built-in project assumptions.
    """
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
        "Retrieve project-scoped review context",
        "Retrieve project-scoped human decision audit context",
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
                    assets_payload = await _run_query(
                        session,
                        _assets_count_query(
                            project_id,
                            runtime_config.clickhouse_database,
                        ),
                        secret_value,
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
            "assets_count": int(
                _required_single_row(assets_payload, "assets count")["assets_count"]
            ),
        },
    }
