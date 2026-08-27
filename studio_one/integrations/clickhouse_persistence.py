"""Direct ClickHouse application persistence for controlled writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import clickhouse_connect
from google.cloud import secretmanager

from studio_one.config import StudioOneConfig


PROJECT_COLUMNS = [
    "project_id",
    "title",
    "status",
    "current_canon_version",
    "authority_level",
    "authoritative_source",
    "source_reference",
    "source_version",
    "approval_status",
    "state_version",
    "approved_decision_id",
    "production_constraints",
    "initial_creative_intent",
]


@dataclass(frozen=True)
class ProjectCreateRecord:
    title: str
    initial_creative_intent: str
    production_constraints: str = ""
    source_reference: str = "creator_project_creation_request"
    source_version: str = ""


@dataclass(frozen=True)
class CreatedProjectRecord:
    project_id: str
    title: str
    status: str
    current_canon_version: str
    authority_level: str
    authoritative_source: str
    source_reference: str
    source_version: str
    approval_status: str
    state_version: int
    approved_decision_id: None
    production_constraints: str
    initial_creative_intent: str


class ClickHouseInsertClient(Protocol):
    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str],
        database: str | None = None,
    ) -> Any:
        """Insert rows into ClickHouse."""


def get_clickhouse_password(config: StudioOneConfig | None = None) -> str:
    runtime_config = config or StudioOneConfig.from_env()
    client = secretmanager.SecretManagerServiceClient()
    name = (
        f"projects/{runtime_config.google_cloud_project}/secrets/"
        f"{runtime_config.clickhouse_password_secret}/versions/latest"
    )
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def build_clickhouse_client(
    config: StudioOneConfig | None = None,
) -> ClickHouseInsertClient:
    runtime_config = config or StudioOneConfig.from_env()
    return clickhouse_connect.get_client(
        host=runtime_config.clickhouse_host,
        port=runtime_config.clickhouse_port,
        username=runtime_config.clickhouse_user,
        password=get_clickhouse_password(runtime_config),
        database=runtime_config.clickhouse_database,
        secure=runtime_config.clickhouse_secure,
        verify=runtime_config.clickhouse_verify,
    )


class ClickHouseProjectPersistence:
    """Application-owned writer for new project records."""

    def __init__(
        self,
        client: ClickHouseInsertClient | None = None,
        config: StudioOneConfig | None = None,
    ) -> None:
        self._config = config or StudioOneConfig.from_env()
        self._client = client or build_clickhouse_client(self._config)

    def create_project(self, record: ProjectCreateRecord) -> CreatedProjectRecord:
        title = record.title.strip()
        if not title:
            raise ValueError("project title is required")
        initial_creative_intent = record.initial_creative_intent.strip()
        if not initial_creative_intent:
            raise ValueError("initial_creative_intent is required")

        created = CreatedProjectRecord(
            project_id=str(uuid4()),
            title=title,
            status="active_in_development",
            current_canon_version="",
            authority_level="creator_supplied_project_context",
            authoritative_source="creator",
            source_reference=record.source_reference.strip()
            or "creator_project_creation_request",
            source_version=record.source_version.strip(),
            approval_status="creator_supplied",
            state_version=1,
            approved_decision_id=None,
            production_constraints=record.production_constraints.strip(),
            initial_creative_intent=initial_creative_intent,
        )

        row = [
            created.project_id,
            created.title,
            created.status,
            created.current_canon_version,
            created.authority_level,
            created.authoritative_source,
            created.source_reference,
            created.source_version,
            created.approval_status,
            created.state_version,
            created.approved_decision_id,
            created.production_constraints,
            created.initial_creative_intent,
        ]
        self._client.insert(
            "projects",
            [row],
            column_names=PROJECT_COLUMNS,
            database=self._config.clickhouse_database,
        )
        return created
