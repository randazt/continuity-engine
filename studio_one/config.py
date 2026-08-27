"""Runtime configuration for STUDIO//ONE."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StudioOneConfig:
    google_cloud_project: str
    google_cloud_location: str
    gemini_model: str
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_database: str
    clickhouse_password_secret: str
    clickhouse_secure: bool
    clickhouse_verify: bool
    mcp_query_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "StudioOneConfig":
        return cls(
            google_cloud_project=os.getenv(
                "GOOGLE_CLOUD_PROJECT",
                "continuity-engine-506601",
            ),
            google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            clickhouse_host=os.getenv(
                "CLICKHOUSE_HOST",
                "hoe2r5j8zb.us-east1.gcp.clickhouse.cloud",
            ),
            clickhouse_port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
            clickhouse_user=os.getenv("CLICKHOUSE_USER", "default"),
            clickhouse_database=os.getenv("CLICKHOUSE_DATABASE", "continuity_engine"),
            clickhouse_password_secret=os.getenv(
                "CLICKHOUSE_PASSWORD_SECRET",
                "clickhouse-password",
            ),
            clickhouse_secure=_bool_env("CLICKHOUSE_SECURE", default=True),
            clickhouse_verify=_bool_env("CLICKHOUSE_VERIFY", default=True),
            mcp_query_timeout_seconds=int(
                os.getenv("CLICKHOUSE_MCP_QUERY_TIMEOUT", "90")
            ),
        )


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def mcp_python_executable() -> Path | str:
    configured = os.getenv("MCP_CLICKHOUSE_PYTHON")
    if configured:
        return configured

    repo_python = repo_root() / ".venv" / "Scripts" / "python.exe"
    if repo_python.exists():
        return repo_python

    return sys.executable


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
