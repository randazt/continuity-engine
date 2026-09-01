"""Runtime configuration for STUDIO//ONE."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_RUNTIME_ENV_VARS = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GEMINI_MODEL",
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_DATABASE",
    "CLICKHOUSE_PASSWORD_SECRET",
)


class MissingRuntimeConfigError(RuntimeError):
    """Raised when deployment/runtime configuration is incomplete."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = tuple(sorted(missing))
        super().__init__(
            "Missing required runtime environment variables: "
            + ", ".join(self.missing)
        )


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
        load_runtime_dotenv()
        missing = [
            name for name in REQUIRED_RUNTIME_ENV_VARS if not _env_value(name)
        ]
        if missing:
            raise MissingRuntimeConfigError(missing)

        return cls(
            google_cloud_project=_required_env("GOOGLE_CLOUD_PROJECT"),
            google_cloud_location=_required_env("GOOGLE_CLOUD_LOCATION"),
            gemini_model=_required_env("GEMINI_MODEL"),
            clickhouse_host=_required_env("CLICKHOUSE_HOST"),
            clickhouse_port=_int_env("CLICKHOUSE_PORT", default=8443),
            clickhouse_user=_required_env("CLICKHOUSE_USER"),
            clickhouse_database=_required_env("CLICKHOUSE_DATABASE"),
            clickhouse_password_secret=_required_env(
                "CLICKHOUSE_PASSWORD_SECRET"
            ),
            clickhouse_secure=_bool_env("CLICKHOUSE_SECURE", default=True),
            clickhouse_verify=_bool_env("CLICKHOUSE_VERIFY", default=True),
            mcp_query_timeout_seconds=_int_env(
                "CLICKHOUSE_MCP_QUERY_TIMEOUT",
                default=90,
            ),
        )


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_runtime_dotenv() -> None:
    """Load local .env values for development; Cloud Run uses real env vars."""
    if not _bool_env("STUDIO_ONE_LOAD_DOTENV", default=True):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(repo_root() / ".env", override=False)


def mcp_python_executable() -> str:
    configured = _env_value("MCP_CLICKHOUSE_PYTHON")
    if configured:
        return configured
    return sys.executable


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _required_env(name: str) -> str:
    value = _env_value(name)
    if not value:
        raise MissingRuntimeConfigError([name])
    return value


def _int_env(name: str, default: int) -> int:
    value = _env_value(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
