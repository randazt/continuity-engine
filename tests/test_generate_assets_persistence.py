from __future__ import annotations

import inspect
import json
import re
import unittest
from typing import Any

from studio_one.integrations import clickhouse_mcp
from studio_one.integrations.clickhouse_mcp import _external_asset_candidate_query
from studio_one.integrations.clickhouse_mcp import _generation_package_query
from studio_one.integrations.clickhouse_persistence import (
    EXTERNAL_ASSET_AUTHORITY_LEVEL,
    EXTERNAL_ASSET_INTAKE_COLUMNS,
    EXTERNAL_ASSET_INTAKE_STATUS,
    EXTERNAL_ASSET_QC_STATUS,
    GENERATION_PACKAGE_AUTHORITY_LEVEL,
    GENERATION_PACKAGE_COLUMNS,
    GENERATION_PACKAGE_STATUS,
    ClickHouseExternalAssetIntakePersistence,
    ClickHouseGenerationPackagePersistence,
    ExternalAssetIntakeRecord,
    GenerationPackageCreateRecord,
)
from studio_one.services.asset_intake_service import ExternalAssetIntakeRequest
from studio_one.services.asset_intake_service import ExternalAssetIntakeService
from studio_one.services.generate_assets_service import GenerateAssetsRequest
from studio_one.services.generate_assets_service import GenerateAssetsService

from test_generate_assets_slice import PROJECT_ID
from test_generate_assets_slice import STORYBOARD_ID
from test_generate_assets_slice import valid_generate_assets_output
from test_project_creation_slice import TEST_CONFIG


class FakeQueryResult:
    def __init__(self, column_names: list[str], rows: list[list[Any]]) -> None:
        self.column_names = column_names
        self.result_rows = rows


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "storyboards": [
                {
                    "storyboard_id": STORYBOARD_ID,
                    "project_id": PROJECT_ID,
                    "storyboard_version": 1,
                    "status": "approved",
                    "approval_status": "approved",
                    "authority_level": "approved_production_state",
                }
            ],
            "generation_packages": [],
            "external_asset_intake": [],
            "assets": [],
            "review_queue": [],
            "decision_log": [],
        }

    def insert(
        self,
        table: str,
        data: list[list[Any]],
        column_names: list[str],
        database: str | None = None,
    ) -> None:
        for row in data:
            self.tables.setdefault(table, []).append(dict(zip(column_names, row)))

    def query(self, query: str) -> FakeQueryResult:
        if ".`storyboards`" in query:
            project_id, storyboard_id = _uuids(query)[:2]
            storyboard_version = _number_assignment(query, "storyboard_version")
            rows = [
                row
                for row in self.tables["storyboards"]
                if row["project_id"] == project_id
                and row["storyboard_id"] == storyboard_id
                and row["storyboard_version"] == storyboard_version
                and row["status"] == "approved"
                and row["approval_status"] == "approved"
                and row["authority_level"] == "approved_production_state"
            ]
            return _result(
                [
                    "storyboard_id",
                    "project_id",
                    "storyboard_version",
                    "status",
                    "approval_status",
                    "authority_level",
                ],
                rows,
            )

        if ".`generation_packages`" in query:
            rows = list(self.tables["generation_packages"])
            project_id = _uuids(query)[0]
            rows = [row for row in rows if row["project_id"] == project_id]
            if "generation_package_id =" in query:
                package_id = _uuids(query)[1]
                package_version = _number_assignment(query, "package_version")
                rows = [
                    row
                    for row in rows
                    if row["generation_package_id"] == package_id
                    and row["package_version"] == package_version
                ]
            else:
                storyboard_id = _uuids(query)[1]
                storyboard_version = _number_assignment(
                    query,
                    "approved_storyboard_version",
                )
                storyboard_reference = _string_assignment(
                    query,
                    "storyboard_panel_shot_reference",
                )
                package_type = _string_assignment(query, "package_type")
                rows = [
                    row
                    for row in rows
                    if row["approved_storyboard_id"] == storyboard_id
                    and row["approved_storyboard_version"] == storyboard_version
                    and row["storyboard_panel_shot_reference"] == storyboard_reference
                    and row["package_type"] == package_type
                ]
                rows = sorted(
                    rows,
                    key=lambda row: (row["package_version"], row["generation_package_id"]),
                    reverse=True,
                )
            return _result(
                [
                    "generation_package_id",
                    "project_id",
                    "approved_storyboard_id",
                    "approved_storyboard_version",
                    "storyboard_panel_shot_reference",
                    "package_type",
                    "package_version",
                    "status",
                    "authority_level",
                    "package_json",
                    "supersedes_generation_package_id",
                ],
                rows,
            )

        if ".`external_asset_intake`" in query:
            project_id, candidate_id = _uuids(query)[:2]
            rows = [
                row
                for row in self.tables["external_asset_intake"]
                if row["project_id"] == project_id
                and row["external_asset_candidate_id"] == candidate_id
            ]
            return _result(
                [
                    "external_asset_candidate_id",
                    "project_id",
                    "source_generation_package_id",
                    "source_generation_package_version",
                    "approved_storyboard_id",
                    "approved_storyboard_version",
                    "storyboard_panel_shot_reference",
                    "asset_type",
                    "external_asset_reference",
                    "intake_status",
                    "qc_status",
                    "authority_level",
                    "supersedes_external_asset_candidate_id",
                    "retry_of_external_asset_candidate_id",
                ],
                rows,
            )

        raise AssertionError(f"Unexpected query: {query}")

    def command(self, command: str) -> None:
        raise AssertionError(f"Unexpected command: {command}")


def _result(columns: list[str], rows: list[dict[str, Any]]) -> FakeQueryResult:
    return FakeQueryResult(
        columns,
        [[row.get(column) for column in columns] for row in rows],
    )


def _uuids(text: str) -> list[str]:
    return re.findall(r"toUUID\('([^']+)'\)", text)


def _number_assignment(text: str, field: str) -> int:
    match = re.search(rf"{field}\s*=\s*(\d+)", text)
    if not match:
        raise AssertionError(f"Missing number assignment for {field}: {text}")
    return int(match.group(1))


def _string_assignment(text: str, field: str) -> str:
    match = re.search(rf"{field}\s*=\s*'((?:\\'|[^'])*)'", text)
    if not match:
        raise AssertionError(f"Missing string assignment for {field}: {text}")
    return match.group(1).replace("\\'", "'").replace("\\\\", "\\")


def _package_persistence(
    client: FakeClickHouseClient,
) -> ClickHouseGenerationPackagePersistence:
    return ClickHouseGenerationPackagePersistence(client=client, config=TEST_CONFIG)


def _intake_persistence(
    client: FakeClickHouseClient,
) -> ClickHouseExternalAssetIntakePersistence:
    return ClickHouseExternalAssetIntakePersistence(client=client, config=TEST_CONFIG)


def _persist_package(client: FakeClickHouseClient) -> list[Any]:
    return _package_persistence(client).persist_generate_assets_package(
        GenerationPackageCreateRecord(
            project_id=PROJECT_ID,
            package={"structured_output": valid_generate_assets_output()},
            source_reference="generate_assets_agent",
            evidence_references=("mcp:project-memory",),
            gemini_model="gemini-2.5-flash",
        )
    )


class GenerationPackagePersistenceTests(unittest.TestCase):
    def test_persists_prompt_and_handoff_rows_without_assets(self) -> None:
        client = FakeClickHouseClient()

        created = _persist_package(client)

        self.assertEqual(len(created), 4)
        self.assertEqual(len(client.tables["generation_packages"]), 4)
        self.assertEqual(client.tables["assets"], [])
        self.assertEqual(client.tables["review_queue"], [])
        self.assertEqual(client.tables["decision_log"], [])
        self.assertEqual(
            {row["package_type"] for row in client.tables["generation_packages"]},
            {
                "image_prompt",
                "video_prompt",
                "dialogue_audio_handoff",
                "sound_music_handoff",
            },
        )
        for row in client.tables["generation_packages"]:
            self.assertEqual(set(row), set(GENERATION_PACKAGE_COLUMNS))
            self.assertEqual(row["status"], GENERATION_PACKAGE_STATUS)
            self.assertEqual(row["authority_level"], GENERATION_PACKAGE_AUTHORITY_LEVEL)
            payload = json.loads(row["package_json"])
            self.assertFalse(payload["generation_prompt_is_asset"])
            self.assertEqual(payload["project_id"], PROJECT_ID)
            self.assertEqual(payload["approved_storyboard_id"], STORYBOARD_ID)
            self.assertEqual(payload["approved_storyboard_version"], 1)

    def test_generation_package_provenance_mismatch_fails_closed(self) -> None:
        client = FakeClickHouseClient()
        payload = valid_generate_assets_output()
        payload["approved_storyboard_id"] = "33333333-3333-4333-8333-333333333333"

        with self.assertRaises(ValueError):
            _package_persistence(client).persist_generate_assets_package(
                GenerationPackageCreateRecord(
                    project_id=PROJECT_ID,
                    package={"structured_output": payload},
                )
            )

        self.assertEqual(client.tables["generation_packages"], [])

    def test_identical_retry_does_not_duplicate_generation_packages(self) -> None:
        client = FakeClickHouseClient()

        first = _persist_package(client)
        second = _persist_package(client)

        self.assertEqual(len(client.tables["generation_packages"]), 4)
        self.assertEqual(
            [row.generation_package_id for row in first],
            [row.generation_package_id for row in second],
        )

    def test_changed_package_creates_next_version_and_supersedes_previous(self) -> None:
        client = FakeClickHouseClient()
        first = _persist_package(client)
        payload = valid_generate_assets_output()
        payload["image_prompt_packages"][0][
            "positive_image_prompt"
        ] = "Revised provider-neutral image instructions."

        second = _package_persistence(client).persist_generate_assets_package(
            GenerationPackageCreateRecord(
                project_id=PROJECT_ID,
                package={"structured_output": payload},
            )
        )

        image_rows = [
            row
            for row in client.tables["generation_packages"]
            if row["package_type"] == "image_prompt"
        ]
        self.assertEqual(len(image_rows), 2)
        revised = [
            row for row in second if row.package_type == "image_prompt"
        ][0]
        original = [
            row for row in first if row.package_type == "image_prompt"
        ][0]
        self.assertEqual(revised.package_version, 2)
        self.assertEqual(
            revised.supersedes_generation_package_id,
            original.generation_package_id,
        )


class ExternalAssetIntakeTests(unittest.TestCase):
    def test_creator_intake_creates_candidate_only(self) -> None:
        client = FakeClickHouseClient()
        package = [
            row for row in _persist_package(client) if row.package_type == "image_prompt"
        ][0]

        candidate = _intake_persistence(client).submit_external_asset_candidate(
            ExternalAssetIntakeRecord(
                project_id=PROJECT_ID,
                source_generation_package_id=package.generation_package_id,
                source_generation_package_version=package.package_version,
                approved_storyboard_id=STORYBOARD_ID,
                approved_storyboard_version=1,
                storyboard_panel_shot_reference="panel 1",
                asset_type="image",
                external_asset_reference="creator-submitted://image-001",
                creator_supplied_metadata={"format": "png"},
                submitted_by="creator@example.com",
            )
        )

        self.assertEqual(len(client.tables["external_asset_intake"]), 1)
        self.assertEqual(client.tables["assets"], [])
        row = client.tables["external_asset_intake"][0]
        self.assertEqual(set(row), set(EXTERNAL_ASSET_INTAKE_COLUMNS))
        self.assertEqual(row["intake_status"], EXTERNAL_ASSET_INTAKE_STATUS)
        self.assertEqual(row["qc_status"], EXTERNAL_ASSET_QC_STATUS)
        self.assertEqual(row["authority_level"], EXTERNAL_ASSET_AUTHORITY_LEVEL)
        self.assertEqual(candidate.intake_status, "submitted_for_qc")
        self.assertEqual(candidate.qc_status, "pending_qc")

    def test_intake_package_storyboard_reference_mismatch_fails_closed(self) -> None:
        client = FakeClickHouseClient()
        package = [
            row for row in _persist_package(client) if row.package_type == "image_prompt"
        ][0]

        with self.assertRaises(ValueError):
            _intake_persistence(client).submit_external_asset_candidate(
                ExternalAssetIntakeRecord(
                    project_id=PROJECT_ID,
                    source_generation_package_id=package.generation_package_id,
                    source_generation_package_version=package.package_version,
                    approved_storyboard_id=STORYBOARD_ID,
                    approved_storyboard_version=1,
                    storyboard_panel_shot_reference="panel 2",
                    asset_type="image",
                    external_asset_reference="creator-submitted://image-001",
                    submitted_by="creator@example.com",
                )
            )

        self.assertEqual(client.tables["external_asset_intake"], [])
        self.assertEqual(client.tables["assets"], [])

    def test_retry_candidate_does_not_overwrite_previous_candidate(self) -> None:
        client = FakeClickHouseClient()
        package = [
            row for row in _persist_package(client) if row.package_type == "image_prompt"
        ][0]
        persistence = _intake_persistence(client)
        first = persistence.submit_external_asset_candidate(
            ExternalAssetIntakeRecord(
                project_id=PROJECT_ID,
                source_generation_package_id=package.generation_package_id,
                source_generation_package_version=package.package_version,
                approved_storyboard_id=STORYBOARD_ID,
                approved_storyboard_version=1,
                storyboard_panel_shot_reference="panel 1",
                asset_type="image",
                external_asset_reference="creator-submitted://image-001",
                submitted_by="creator@example.com",
            )
        )

        second = persistence.submit_external_asset_candidate(
            ExternalAssetIntakeRecord(
                project_id=PROJECT_ID,
                source_generation_package_id=package.generation_package_id,
                source_generation_package_version=package.package_version,
                approved_storyboard_id=STORYBOARD_ID,
                approved_storyboard_version=1,
                storyboard_panel_shot_reference="panel 1",
                asset_type="image",
                external_asset_reference="creator-submitted://image-002",
                submitted_by="creator@example.com",
                retry_of_external_asset_candidate_id=first.external_asset_candidate_id,
            )
        )

        self.assertEqual(len(client.tables["external_asset_intake"]), 2)
        self.assertNotEqual(
            first.external_asset_candidate_id,
            second.external_asset_candidate_id,
        )
        self.assertEqual(
            second.retry_of_external_asset_candidate_id,
            first.external_asset_candidate_id,
        )
        self.assertEqual(client.tables["external_asset_intake"][0]["qc_status"], "pending_qc")
        self.assertEqual(client.tables["assets"], [])

    def test_service_does_not_accept_approval_status_from_creator_or_gemini(self) -> None:
        client = FakeClickHouseClient()
        package = [
            row for row in _persist_package(client) if row.package_type == "image_prompt"
        ][0]
        service = ExternalAssetIntakeService(writer=_intake_persistence(client))

        result = service.submit_candidate_for_qc(
            ExternalAssetIntakeRequest(
                project_id=PROJECT_ID,
                source_generation_package_id=package.generation_package_id,
                source_generation_package_version=package.package_version,
                approved_storyboard_id=STORYBOARD_ID,
                approved_storyboard_version=1,
                storyboard_panel_shot_reference="panel 1",
                asset_type="image",
                external_asset_reference="creator-submitted://image-003",
                submitted_by="creator@example.com",
            )
        )

        self.assertEqual(result.stage, "quality_control")
        self.assertNotIn("approved_for_promotion", result.candidate)
        self.assertEqual(result.candidate["qc_status"], "pending_qc")
        self.assertEqual(client.tables["assets"], [])


class GenerateAssetsServicePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_assets_service_persists_packages_when_writer_is_configured(
        self,
    ) -> None:
        client = FakeClickHouseClient()

        async def fake_runner(**_: object) -> dict[str, object]:
            return {
                "runtime": {
                    "gemini_model_used": "gemini-2.5-flash",
                    "clickhouse_writes_performed": False,
                },
                "structured_output": valid_generate_assets_output(),
            }

        service = GenerateAssetsService(
            generate_assets_runner=fake_runner,
            generation_package_writer=_package_persistence(client),
        )

        result = await service.generate_assets_package(
            GenerateAssetsRequest(project_id=PROJECT_ID)
        )

        self.assertEqual(len(result.persisted_generation_packages), 4)
        self.assertEqual(len(client.tables["generation_packages"]), 4)
        self.assertEqual(client.tables["assets"], [])
        self.assertEqual(client.tables["decision_log"], [])


class McpProvenanceRetrievalTests(unittest.TestCase):
    def test_generation_package_query_retrieves_exact_instruction_row(self) -> None:
        query = _generation_package_query(
            PROJECT_ID,
            "44444444-4444-4444-8444-444444444444",
            2,
            "test_db",
        )

        self.assertIn("FROM `test_db`.`generation_packages`", query)
        self.assertIn("generation_package_id =", query)
        self.assertIn("package_version = 2", query)
        self.assertIn("status = 'instructions_for_creator'", query)
        self.assertIn("authority_level = 'production_instruction'", query)

    def test_external_asset_candidate_query_retrieves_pending_qc_candidate(self) -> None:
        query = _external_asset_candidate_query(
            PROJECT_ID,
            "55555555-5555-4555-8555-555555555555",
            "test_db",
        )

        self.assertIn("FROM `test_db`.`external_asset_intake`", query)
        self.assertIn("external_asset_candidate_id =", query)
        self.assertIn("intake_status = 'submitted_for_qc'", query)
        self.assertIn("qc_status = 'pending_qc'", query)
        self.assertIn("authority_level = 'external_asset_candidate'", query)

    def test_mcp_bundle_includes_optional_qc_provenance_chain(self) -> None:
        source = inspect.getsource(clickhouse_mcp)

        self.assertIn("_generation_package_query", source)
        self.assertIn("_external_asset_candidate_query", source)
        self.assertIn('"generation_package": _optional_single_row', source)
        self.assertIn('"external_asset_candidate": _optional_single_row', source)
        self.assertIn("CLICKHOUSE_ALLOW_WRITE_ACCESS", source)
        self.assertIn('"false"', source)


if __name__ == "__main__":
    unittest.main()
