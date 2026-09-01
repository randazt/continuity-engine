from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from studio_one.config import MissingRuntimeConfigError
from studio_one.config import REQUIRED_RUNTIME_ENV_VARS
from studio_one.config import StudioOneConfig
from studio_one.config import mcp_python_executable
from studio_one.integrations.clickhouse_mcp import build_mcp_child_environment
from studio_one.integrations.clickhouse_mcp import build_mcp_server_parameters
from studio_one.web.app import create_app
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS


VALID_ENV = {
    "STUDIO_ONE_LOAD_DOTENV": "false",
    "GOOGLE_CLOUD_PROJECT": "project-id",
    "GOOGLE_CLOUD_LOCATION": "us-central1",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "CLICKHOUSE_HOST": "clickhouse.example.com",
    "CLICKHOUSE_USER": "clickhouse-user",
    "CLICKHOUSE_DATABASE": "clickhouse_database",
    "CLICKHOUSE_PASSWORD_SECRET": "clickhouse-password-secret",
}


class CloudRunConfigTests(unittest.TestCase):
    def test_missing_required_runtime_configuration_fails_clearly(self) -> None:
        with patch.dict(os.environ, {"STUDIO_ONE_LOAD_DOTENV": "false"}, clear=True):
            with self.assertRaises(MissingRuntimeConfigError) as raised:
                StudioOneConfig.from_env()

        self.assertEqual(set(raised.exception.missing), set(REQUIRED_RUNTIME_ENV_VARS))
        for name in REQUIRED_RUNTIME_ENV_VARS:
            self.assertIn(name, str(raised.exception))
        self.assertNotIn("clickhouse.example.com", str(raised.exception))

    def test_runtime_configuration_uses_environment_without_secret_values(self) -> None:
        with patch.dict(os.environ, VALID_ENV, clear=True):
            config = StudioOneConfig.from_env()

        self.assertEqual(config.google_cloud_project, "project-id")
        self.assertEqual(config.google_cloud_location, "us-central1")
        self.assertEqual(config.gemini_model, "gemini-2.5-flash")
        self.assertEqual(config.clickhouse_host, "clickhouse.example.com")
        self.assertEqual(config.clickhouse_port, 8443)
        self.assertEqual(config.clickhouse_user, "clickhouse-user")
        self.assertEqual(config.clickhouse_database, "clickhouse_database")
        self.assertEqual(
            config.clickhouse_password_secret,
            "clickhouse-password-secret",
        )

    def test_web_app_imports_without_runtime_config_or_secrets(self) -> None:
        env = os.environ.copy()
        for name in REQUIRED_RUNTIME_ENV_VARS:
            env.pop(name, None)
        env["STUDIO_ONE_LOAD_DOTENV"] = "false"

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from studio_one.web.app import app; print(app.title)",
            ],
            cwd=Path.cwd(),
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STUDIO//ONE", result.stdout)


class CloudRunHealthTests(unittest.TestCase):
    def test_health_endpoint_returns_success_without_dependencies(self) -> None:
        with patch.dict(os.environ, {"STUDIO_ONE_LOAD_DOTENV": "false"}, clear=True):
            client = TestClient(create_app())
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(
            response.json()["checks"]["workflow_stage_count"],
            len(CANONICAL_STAGE_IDENTIFIERS),
        )

    def test_ready_endpoint_reports_missing_config_without_secret_lookup(self) -> None:
        with patch.dict(os.environ, {"STUDIO_ONE_LOAD_DOTENV": "false"}, clear=True):
            client = TestClient(create_app())
            response = client.get("/ready")

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(
            set(payload["missing_environment_variables"]),
            set(REQUIRED_RUNTIME_ENV_VARS),
        )
        self.assertEqual(
            payload["checks"]["runtime_configuration"],
            "missing_required_environment",
        )

    def test_ready_endpoint_succeeds_with_config_and_installed_mcp_package(self) -> None:
        with patch.dict(os.environ, VALID_ENV, clear=True):
            client = TestClient(create_app())
            response = client.get("/ready")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["checks"]["runtime_configuration"], "ok")
        self.assertEqual(payload["checks"]["mcp_clickhouse_package"], "available")
        self.assertEqual(payload["checks"]["secret_manager"], "not_checked")
        self.assertEqual(payload["checks"]["gemini"], "not_checked")
        self.assertEqual(payload["checks"]["clickhouse"], "not_checked")


class CloudRunMcpTests(unittest.TestCase):
    def test_mcp_launch_path_uses_active_python_not_windows_venv_path(self) -> None:
        with patch.dict(os.environ, VALID_ENV, clear=True):
            self.assertEqual(mcp_python_executable(), sys.executable)
            config = StudioOneConfig.from_env()
            params = build_mcp_server_parameters(config, "secret-value")

        self.assertEqual(params.command, sys.executable)
        self.assertEqual(params.args, ["-m", "mcp_clickhouse.main"])
        self.assertNotIn("secret-value", params.command)
        self.assertNotIn("secret-value", " ".join(params.args))

        config_source = Path("studio_one/config.py").read_text(encoding="utf-8")
        self.assertNotIn(".venv", config_source)
        self.assertNotIn("Scripts", config_source)
        self.assertIn("sys.executable", config_source)

    def test_mcp_environment_remains_read_only(self) -> None:
        with patch.dict(os.environ, VALID_ENV, clear=True):
            config = StudioOneConfig.from_env()
            child_env = build_mcp_child_environment(config, "secret-value")

        self.assertEqual(child_env["CLICKHOUSE_ALLOW_WRITE_ACCESS"], "false")
        self.assertEqual(child_env["CLICKHOUSE_ALLOW_DROP"], "false")
        self.assertEqual(child_env["CLICKHOUSE_MCP_SERVER_TRANSPORT"], "stdio")
        self.assertEqual(child_env["CLICKHOUSE_PASSWORD"], "secret-value")


class CloudRunPackagingTests(unittest.TestCase):
    def test_dockerfile_matches_cloud_run_runtime_contract(self) -> None:
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("FROM python:3.12-slim", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements.txt", dockerfile)
        self.assertIn("uvicorn studio_one.web.app:app", dockerfile)
        self.assertIn("--host 0.0.0.0", dockerfile)
        self.assertIn("--port ${PORT:-8080}", dockerfile)
        self.assertIn("EXPOSE 8080", dockerfile)
        self.assertNotIn("COPY .env", dockerfile)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", dockerfile)
        self.assertNotIn("CLICKHOUSE_PASSWORD", dockerfile)

    def test_dockerignore_excludes_local_and_sensitive_files(self) -> None:
        dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

        for expected in (
            ".git",
            ".venv",
            ".env",
            ".env.*",
            "__pycache__",
            "tests",
            "scripts",
        ):
            self.assertIn(expected, dockerignore)

    def test_requirements_include_cloud_run_runtime_packages(self) -> None:
        requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

        self.assertIn("fastapi", requirements)
        self.assertIn("uvicorn[standard]", requirements)
        self.assertIn("google-adk", requirements)
        self.assertIn("google-genai", requirements)
        self.assertIn("google-cloud-secret-manager", requirements)
        self.assertIn("mcp-clickhouse", requirements)
        self.assertIn("clickhouse-connect", requirements)
        self.assertNotIn("openai", requirements)
        self.assertNotIn("anthropic", requirements)
        self.assertNotIn("elevenlabs", requirements)

    def test_frontend_still_exposes_exactly_seven_stages(self) -> None:
        client = TestClient(create_app())

        response = client.get("/api/workflow")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tuple(response.json()["stages"]), CANONICAL_STAGE_IDENTIFIERS)
        self.assertEqual(len(response.json()["stage_labels"]), 7)

    def test_frontend_has_no_direct_clickhouse_access(self) -> None:
        script = Path("studio_one/web/static/app.js").read_text(encoding="utf-8")

        self.assertIn("/api/", script)
        self.assertNotIn("clickhouse", script.lower())
        self.assertNotIn("fetch(\"http", script)
        self.assertNotIn("fetch('http", script)

    def test_no_real_project_or_host_literals_remain_in_runtime_source(self) -> None:
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                Path("studio_one/config.py"),
                Path("studio_one/integrations/clickhouse_mcp.py"),
                Path("scripts/test_clickhouse_mcp.py"),
                Path("README.md"),
                Path(".env.example"),
            ]
        )

        self.assertNotIn("continuity-engine-506601", runtime_text)
        self.assertNotIn("hoe2r5j8zb", runtime_text)
        self.assertNotIn("C:\\Users\\Randa", runtime_text)


if __name__ == "__main__":
    unittest.main()
