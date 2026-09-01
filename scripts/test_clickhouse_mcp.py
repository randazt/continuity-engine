"""Development-only MCP production-memory inspection for ClickHouse Cloud.

This script intentionally prints only sanitized proof output. It retrieves the
ClickHouse password from Google Secret Manager, passes it only to the child
mcp-clickhouse process environment, and never prints the secret value.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any

import anyio
from google.cloud import secretmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from studio_one.config import StudioOneConfig
from studio_one.config import mcp_python_executable
from studio_one.config import repo_root
from studio_one.integrations.clickhouse_mcp import build_mcp_child_environment

EXPECTED_TABLES = [
    "projects",
    "assets",
    "review_queue",
    "decision_log",
    "storyboards",
    "generation_packages",
    "external_asset_intake",
]


def redact(value: Any, secret_value: str | None) -> Any:
    if isinstance(value, str) and secret_value:
        return value.replace(secret_value, "<redacted-clickhouse-password>")
    if isinstance(value, list):
        return [redact(item, secret_value) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secret_value) for key, item in value.items()}
    return value


def print_report(report: dict[str, Any], secret_value: str | None = None) -> None:
    print(json.dumps(redact(report, secret_value), indent=2, sort_keys=True))


def summarize_exception(exc: BaseException, secret_value: str | None) -> Any:
    if isinstance(exc, BaseExceptionGroup):
        return {
            "type": type(exc).__name__,
            "message": redact(str(exc), secret_value),
            "sub_errors": [
                summarize_exception(sub_error, secret_value)
                for sub_error in exc.exceptions
            ],
        }

    return {
        "type": type(exc).__name__,
        "message": redact(str(exc), secret_value),
    }


def get_clickhouse_password(runtime_config: StudioOneConfig) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = (
        f"projects/{runtime_config.google_cloud_project}/secrets/"
        f"{runtime_config.clickhouse_password_secret}/versions/latest"
    )
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def parse_tool_json(call_result: Any, secret_value: str) -> dict[str, Any]:
    if getattr(call_result, "isError", False):
        raise RuntimeError(redact(str(call_result), secret_value))

    content = getattr(call_result, "content", []) or []
    text_items = [
        getattr(item, "text", None)
        for item in content
        if getattr(item, "type", None) == "text" and getattr(item, "text", None)
    ]

    if not text_items:
        structured = getattr(call_result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        raise RuntimeError(redact(str(call_result), secret_value))

    raw_text = text_items[0]
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        raise RuntimeError(redact(raw_text, secret_value)) from None


async def run_query(session: ClientSession, query: str, secret_value: str) -> dict[str, Any]:
    result = await session.call_tool("run_query", {"query": query})
    return parse_tool_json(result, secret_value)


async def run_mcp_inspection(
    runtime_config: StudioOneConfig,
    secret_value: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    root = repo_root()

    params = StdioServerParameters(
        command=str(mcp_python_executable()),
        args=["-m", "mcp_clickhouse.main"],
        env=build_mcp_child_environment(runtime_config, secret_value),
        cwd=str(root),
    )

    with open(os.devnull, "w", encoding="utf-8") as errlog:
        with anyio.fail_after(45):
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=30),
                ) as session:
                    await session.initialize()
                    report["mcp_server_initialized"] = True

                    tools = await session.list_tools()
                    report["tools_discovered"] = [tool.name for tool in tools.tools]

                    database_result = await run_query(
                        session,
                        "SELECT currentDatabase() AS database",
                        secret_value,
                    )
                    database_rows = database_result.get("rows", [])
                    database_name = database_rows[0][0] if database_rows else None
                    report["database_confirmed"] = database_name

                    discovered_result = await run_query(
                        session,
                        (
                            "SELECT name FROM system.tables "
                            f"WHERE database = '{runtime_config.clickhouse_database}' "
                            "ORDER BY name"
                        ),
                        secret_value,
                    )
                    discovered_tables = [row[0] for row in discovered_result.get("rows", [])]
                    report["tables_discovered"] = discovered_tables

                    existing_expected_tables = [
                        table for table in EXPECTED_TABLES if table in discovered_tables
                    ]
                    report["expected_tables"] = {
                        table: table in discovered_tables for table in EXPECTED_TABLES
                    }

                    if existing_expected_tables:
                        quoted_table_names = ", ".join(
                            f"'{table}'" for table in existing_expected_tables
                        )
                        schema_result = await run_query(
                            session,
                            (
                                "SELECT table, name, type, position, default_kind, "
                                "default_expression, comment "
                                "FROM system.columns "
                                f"WHERE database = '{runtime_config.clickhouse_database}' "
                                f"AND table IN ({quoted_table_names}) "
                                "ORDER BY table, position"
                            ),
                            secret_value,
                        )

                        schemas: dict[str, list[dict[str, Any]]] = {
                            table: [] for table in existing_expected_tables
                        }
                        for row in schema_result.get("rows", []):
                            table, name, column_type, position, default_kind, default_expression, comment = row
                            schemas.setdefault(table, []).append(
                                {
                                    "name": name,
                                    "type": column_type,
                                    "position": position,
                                    "default_kind": default_kind,
                                    "default_expression": default_expression,
                                    "comment": comment,
                                }
                            )
                        report["schemas"] = schemas

                        row_counts: dict[str, int] = {}
                        for table in existing_expected_tables:
                            count_result = await run_query(
                                session,
                                (
                                    "SELECT count() AS row_count "
                                    f"FROM `{runtime_config.clickhouse_database}`.`{table}`"
                                ),
                                secret_value,
                            )
                            count_rows = count_result.get("rows", [])
                            row_counts[table] = count_rows[0][0] if count_rows else 0
                        report["row_counts"] = row_counts

                    report["proves_mcp_access_to_production_memory_schema"] = (
                        report["database_confirmed"]
                        == runtime_config.clickhouse_database
                        and all(report["expected_tables"].values())
                        and bool(report["schemas"])
                        and set(report["row_counts"]) == set(EXPECTED_TABLES)
                    )

    return report


async def main() -> None:
    secret_value: str | None = None
    report: dict[str, Any] = {
        "secret_manager_retrieval_succeeded": False,
        "mcp_server_initialized": False,
        "tools_discovered": [],
        "mcp_tool_invoked_for_inspection": "run_query",
        "database_confirmed": None,
        "tables_discovered": [],
        "expected_tables": {},
        "schemas": {},
        "row_counts": {},
        "proves_mcp_access_to_production_memory_schema": False,
    }

    try:
        runtime_config = StudioOneConfig.from_env()
        secret_value = get_clickhouse_password(runtime_config)
        report["secret_manager_retrieval_succeeded"] = True
        report = await run_mcp_inspection(runtime_config, secret_value, report)
    except Exception as exc:
        report["error"] = summarize_exception(exc, secret_value)

    print_report(report, secret_value)


if __name__ == "__main__":
    anyio.run(main)
