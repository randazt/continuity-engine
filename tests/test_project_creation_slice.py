from __future__ import annotations

import inspect
import re
import unittest

from studio_one.agents import refinement_agent
from studio_one.agents.refinement_agent import (
    BrainstormResponse,
    RECOMMENDATION_GOVERNANCE_BOUNDARY,
    STORYBOARD_GOVERNANCE_STATUS,
    StoryboardCandidate,
    StoryboardPanel,
)
from studio_one.config import StudioOneConfig
from studio_one.integrations.clickhouse_mcp import _project_query
from studio_one.integrations.clickhouse_persistence import (
    ClickHouseProjectPersistence,
    CreatedProjectRecord,
    PROJECT_COLUMNS,
    ProjectCreateRecord,
    ProjectTitleUpdateRecord,
    UpdatedProjectTitleRecord,
)
from studio_one.services.project_service import CreateProjectRequest
from studio_one.services.project_service import FinalizeStoryboardRequest
from studio_one.services.project_service import ProjectService
from studio_one.services.project_service import RefineProjectRequest
from studio_one.services.project_service import WorkingTitleSelectionRequest
from studio_one.services import project_service
from studio_one.workflow.stages import CANONICAL_STAGE_IDENTIFIERS
from studio_one.workflow.stages import IMPLEMENTED_STAGE_IDENTIFIERS
from studio_one.workflow.stages import StudioOneStage
from studio_one.workflow.transitions import require_creator_action_transition


TEST_CONFIG = StudioOneConfig(
    google_cloud_project="test-project",
    google_cloud_location="us-central1",
    gemini_model="gemini-2.5-flash",
    clickhouse_host="example.invalid",
    clickhouse_port=8443,
    clickhouse_user="default",
    clickhouse_database="test_db",
    clickhouse_password_secret="clickhouse-password",
    clickhouse_secure=True,
    clickhouse_verify=True,
    mcp_query_timeout_seconds=90,
)


class FakeInsertClient:
    def __init__(self) -> None:
        self.inserts: list[dict[str, object]] = []
        self.commands: list[str] = []

    def insert(
        self,
        table: str,
        data: list[list[object]],
        column_names: list[str],
        database: str | None = None,
    ) -> None:
        self.inserts.append(
            {
                "table": table,
                "data": data,
                "column_names": column_names,
                "database": database,
            }
        )

    def command(self, command: str) -> None:
        self.commands.append(command)


class FakeProjectWriter:
    def __init__(self) -> None:
        self.records: list[ProjectCreateRecord] = []
        self.title_updates: list[ProjectTitleUpdateRecord] = []
        self.created = CreatedProjectRecord(
            project_id="11111111-1111-4111-8111-111111111111",
            title="",
            status="active_in_development",
            current_canon_version="",
            authority_level="creator_supplied_project_context",
            authoritative_source="creator",
            source_reference="creator_project_creation_request",
            source_version="",
            approval_status="creator_supplied",
            state_version=1,
            approved_decision_id=None,
            production_constraints="Use creator-approved visual constraints.",
            initial_creative_intent="Brainstorm a focused short-form idea.",
        )

    def create_project(self, record: ProjectCreateRecord) -> CreatedProjectRecord:
        self.records.append(record)
        return self.created

    def update_project_title(
        self,
        record: ProjectTitleUpdateRecord,
    ) -> UpdatedProjectTitleRecord:
        self.title_updates.append(record)
        return UpdatedProjectTitleRecord(
            project_id=record.project_id,
            title=record.title.strip(),
        )


def fake_stage_report(stage: str, project_id: str) -> dict[str, object]:
    return {
        "stage": stage,
        "runtime": {
            "mcp_retrieval_evidence": {"mcp_tool_invoked": "run_query"},
            "clickhouse_writes_performed": False,
        },
        "validation": {
            "agent_memory_retrieval_path": "official_mcp_clickhouse",
            "gemini_can_advance_stage": False,
            "clickhouse_writes_performed": False,
        },
            "production_memory": {
            "project": {
                "project_id": project_id,
                "title": "",
                "production_constraints": "Use creator-approved visual constraints.",
                "initial_creative_intent": "Brainstorm a focused short-form idea.",
            },
            "assets_count": 0,
        },
        "structured_output": {"stage": stage, "project_id": project_id},
    }


class WorkflowStageTests(unittest.TestCase):
    def test_exactly_seven_canonical_stage_identifiers_exist(self) -> None:
        self.assertEqual(
            CANONICAL_STAGE_IDENTIFIERS,
            (
                "brainstorm",
                "refine",
                "finalize_storyboard",
                "generate_assets",
                "quality_control",
                "post_production",
                "publish",
            ),
        )
        self.assertEqual(len(CANONICAL_STAGE_IDENTIFIERS), 7)
        self.assertEqual(
            IMPLEMENTED_STAGE_IDENTIFIERS,
            (
                "brainstorm",
                "refine",
                "finalize_storyboard",
                "generate_assets",
                "quality_control",
                "post_production",
                "publish",
            ),
        )

    def test_creator_action_is_required_for_brainstorm_to_refine(self) -> None:
        with self.assertRaises(ValueError):
            require_creator_action_transition(
                StudioOneStage.BRAINSTORM,
                StudioOneStage.REFINE,
                " ",
            )

    def test_creator_action_is_required_for_refine_to_finalize_storyboard(self) -> None:
        with self.assertRaises(ValueError):
            require_creator_action_transition(
                StudioOneStage.REFINE,
                StudioOneStage.FINALIZE_STORYBOARD,
                None,
            )


class ProjectCreationPersistenceTests(unittest.TestCase):
    def test_project_creation_writes_exactly_one_project_row(self) -> None:
        client = FakeInsertClient()
        persistence = ClickHouseProjectPersistence(client=client, config=TEST_CONFIG)

        created = persistence.create_project(
            ProjectCreateRecord(
                initial_creative_intent="Brainstorm a focused short-form idea.",
                production_constraints="Use creator-approved visual constraints.",
                source_reference="creator_project_creation_request",
            )
        )

        self.assertEqual(len(client.inserts), 1)
        insert = client.inserts[0]
        self.assertEqual(insert["table"], "projects")
        self.assertEqual(insert["database"], "test_db")
        self.assertEqual(insert["column_names"], PROJECT_COLUMNS)
        self.assertEqual(len(insert["data"]), 1)

        row = dict(zip(PROJECT_COLUMNS, insert["data"][0]))
        self.assertEqual(row["project_id"], created.project_id)
        self.assertEqual(row["title"], "")
        self.assertEqual(row["status"], "active_in_development")
        self.assertEqual(row["production_constraints"], "Use creator-approved visual constraints.")
        self.assertEqual(
            row["initial_creative_intent"],
            "Brainstorm a focused short-form idea.",
        )
        self.assertEqual(row["authority_level"], "creator_supplied_project_context")
        self.assertEqual(row["authoritative_source"], "creator")
        self.assertEqual(row["source_reference"], "creator_project_creation_request")
        self.assertEqual(row["source_version"], "")
        self.assertEqual(row["approval_status"], "creator_supplied")
        self.assertIsNone(row["approved_decision_id"])

    def test_initial_creative_intent_is_not_abused_as_constraints(self) -> None:
        client = FakeInsertClient()
        persistence = ClickHouseProjectPersistence(client=client, config=TEST_CONFIG)
        persistence.create_project(
            ProjectCreateRecord(
                initial_creative_intent="Brainstorm a focused short-form idea.",
                production_constraints="",
            )
        )

        row = dict(zip(PROJECT_COLUMNS, client.inserts[0]["data"][0]))
        self.assertEqual(row["production_constraints"], "")
        self.assertEqual(
            row["initial_creative_intent"],
            "Brainstorm a focused short-form idea.",
        )

    def test_project_creation_accepts_empty_initial_title(self) -> None:
        client = FakeInsertClient()
        persistence = ClickHouseProjectPersistence(client=client, config=TEST_CONFIG)

        created = persistence.create_project(
            ProjectCreateRecord(
                initial_creative_intent="Brainstorm before naming.",
            )
        )

        row = dict(zip(PROJECT_COLUMNS, client.inserts[0]["data"][0]))
        self.assertEqual(created.title, "")
        self.assertEqual(row["title"], "")

    def test_project_creation_ignores_legacy_supplied_title(self) -> None:
        client = FakeInsertClient()
        persistence = ClickHouseProjectPersistence(client=client, config=TEST_CONFIG)

        created = persistence.create_project(
            ProjectCreateRecord(
                title="Should Not Persist Before BRAINSTORM",
                initial_creative_intent="Brainstorm before naming.",
            )
        )

        row = dict(zip(PROJECT_COLUMNS, client.inserts[0]["data"][0]))
        self.assertEqual(created.title, "")
        self.assertEqual(row["title"], "")

    def test_working_title_update_uses_projects_title_only(self) -> None:
        client = FakeInsertClient()
        persistence = ClickHouseProjectPersistence(client=client, config=TEST_CONFIG)

        updated = persistence.update_project_title(
            ProjectTitleUpdateRecord(
                project_id="11111111-1111-4111-8111-111111111111",
                title="Selected Memory Thread",
            )
        )

        self.assertEqual(updated.title, "Selected Memory Thread")
        self.assertEqual(client.inserts, [])
        self.assertEqual(len(client.commands), 1)
        command = client.commands[0]
        self.assertIn("ALTER TABLE `test_db`.`projects`", command)
        self.assertIn("UPDATE title = 'Selected Memory Thread'", command)
        self.assertNotIn("assets", command)
        self.assertNotIn("storyboards", command)
        self.assertNotIn("decision_log", command)


class ProjectServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_creation_starts_workflow_at_brainstorm(self) -> None:
        writer = FakeProjectWriter()
        brainstorm_calls: list[dict[str, object]] = []

        async def fake_brainstorm_runner(**kwargs: object) -> dict[str, object]:
            brainstorm_calls.append(kwargs)
            return fake_stage_report("brainstorm", str(kwargs["project_id"]))

        service = ProjectService(
            project_writer=writer,
            brainstorm_runner=fake_brainstorm_runner,
        )

        result = await service.create_project_and_start_brainstorm(
            CreateProjectRequest(
                production_constraints="Use creator-approved visual constraints.",
                initial_creative_intent="Brainstorm a focused short-form idea.",
            )
        )

        self.assertEqual(len(writer.records), 1)
        self.assertEqual(writer.records[0].title, "")
        self.assertEqual(
            writer.records[0].production_constraints,
            "Use creator-approved visual constraints.",
        )
        self.assertEqual(
            writer.records[0].initial_creative_intent,
            "Brainstorm a focused short-form idea.",
        )
        self.assertEqual(brainstorm_calls, [{"project_id": writer.created.project_id}])
        self.assertEqual(result.stage, StudioOneStage.BRAINSTORM.value)
        self.assertEqual(result.project["approved_decision_id"], None)
        self.assertEqual(
            result.brainstorm["runtime"]["mcp_retrieval_evidence"][
                "mcp_tool_invoked"
            ],
            "run_query",
        )

    async def test_gemini_cannot_autonomously_advance_stage(self) -> None:
        writer = FakeProjectWriter()

        async def fake_brainstorm_runner(**kwargs: object) -> dict[str, object]:
            report = fake_stage_report("brainstorm", str(kwargs["project_id"]))
            report["structured_output"] = {
                "stage": "brainstorm",
                "model_recommendation": "Ready to refine.",
            }
            return report

        async def forbidden_refine_runner(**_: object) -> dict[str, object]:
            raise AssertionError("REFINE must not run without creator action")

        service = ProjectService(
            project_writer=writer,
            brainstorm_runner=fake_brainstorm_runner,
            refine_runner=forbidden_refine_runner,
        )

        result = await service.create_project_and_start_brainstorm(
            CreateProjectRequest(
                initial_creative_intent="Brainstorm a focused short-form idea.",
            )
        )

        self.assertEqual(result.stage, StudioOneStage.BRAINSTORM.value)
        self.assertEqual(writer.records[0].title, "")

    async def test_project_creation_accepts_only_initial_creative_intent(self) -> None:
        writer = FakeProjectWriter()

        async def fake_brainstorm_runner(**kwargs: object) -> dict[str, object]:
            return fake_stage_report("brainstorm", str(kwargs["project_id"]))

        service = ProjectService(
            project_writer=writer,
            brainstorm_runner=fake_brainstorm_runner,
        )

        result = await service.create_project_and_start_brainstorm(
            CreateProjectRequest(
                initial_creative_intent="A memory-led short film about a studio.",
            )
        )

        self.assertEqual(result.stage, StudioOneStage.BRAINSTORM.value)
        self.assertEqual(len(writer.records), 1)
        self.assertEqual(writer.records[0].title, "")
        self.assertEqual(writer.records[0].production_constraints, "")
        self.assertEqual(
            writer.records[0].initial_creative_intent,
            "A memory-led short film about a studio.",
        )

    async def test_creator_can_select_working_title_without_approval_side_effects(self) -> None:
        writer = FakeProjectWriter()
        service = ProjectService(project_writer=writer)

        result = service.select_working_title(
            WorkingTitleSelectionRequest(
                project_id="11111111-1111-4111-8111-111111111111",
                title="Selected Memory Thread",
            )
        )

        self.assertEqual(result.title, "Selected Memory Thread")
        self.assertEqual(writer.title_updates[0].title, "Selected Memory Thread")
        self.assertFalse(result.asset_created)
        self.assertFalse(result.storyboard_approval_created)
        self.assertFalse(result.canon_approval_created)
        self.assertEqual(result.approval_status, "creator_supplied")

    async def test_refine_requires_explicit_creator_direction(self) -> None:
        service = ProjectService(project_writer=FakeProjectWriter())

        with self.assertRaises(ValueError):
            await service.refine_project(
                RefineProjectRequest(
                    project_id="11111111-1111-4111-8111-111111111111",
                    creator_direction=" ",
                )
            )

    async def test_refine_retrieves_production_memory_through_stage_runner(self) -> None:
        refine_calls: list[dict[str, object]] = []

        async def fake_refine_runner(**kwargs: object) -> dict[str, object]:
            refine_calls.append(kwargs)
            return fake_stage_report("refine", str(kwargs["project_id"]))

        service = ProjectService(
            project_writer=FakeProjectWriter(),
            refine_runner=fake_refine_runner,
        )

        result = await service.refine_project(
            RefineProjectRequest(
                project_id="11111111-1111-4111-8111-111111111111",
                creator_direction="Use the second direction and make it quieter.",
            )
        )

        self.assertEqual(
            refine_calls,
            [
                {
                    "project_id": "11111111-1111-4111-8111-111111111111",
                    "creator_direction": "Use the second direction and make it quieter.",
                }
            ],
        )
        self.assertEqual(result.stage, StudioOneStage.REFINE.value)
        self.assertEqual(
            result.refinement["validation"]["agent_memory_retrieval_path"],
            "official_mcp_clickhouse",
        )

    async def test_finalize_storyboard_requires_explicit_creator_action(self) -> None:
        service = ProjectService(project_writer=FakeProjectWriter())

        with self.assertRaises(ValueError):
            await service.finalize_storyboard_candidate(
                FinalizeStoryboardRequest(
                    project_id="11111111-1111-4111-8111-111111111111",
                    creator_action=" ",
                )
            )

    async def test_storyboard_generation_creates_no_assets_or_fake_decision(self) -> None:
        storyboard_calls: list[dict[str, object]] = []

        async def fake_storyboard_runner(**kwargs: object) -> dict[str, object]:
            storyboard_calls.append(kwargs)
            return fake_stage_report("finalize_storyboard", str(kwargs["project_id"]))

        service = ProjectService(
            project_writer=FakeProjectWriter(),
            storyboard_runner=fake_storyboard_runner,
        )

        result = await service.finalize_storyboard_candidate(
            FinalizeStoryboardRequest(
                project_id="11111111-1111-4111-8111-111111111111",
                creator_action="Prepare the storyboard candidate for review.",
                target_total_runtime="60 seconds",
            )
        )

        self.assertEqual(
            storyboard_calls,
            [
                {
                    "project_id": "11111111-1111-4111-8111-111111111111",
                    "creator_action": "Prepare the storyboard candidate for review.",
                    "target_total_runtime": "60 seconds",
                }
            ],
        )
        self.assertEqual(result.stage, StudioOneStage.FINALIZE_STORYBOARD.value)
        self.assertFalse(
            result.storyboard_candidate["runtime"]["clickhouse_writes_performed"]
        )


class AgentContractTests(unittest.TestCase):
    def test_brainstorm_and_refine_schemas_are_structured_contracts(self) -> None:
        self.assertTrue(
            {
                "creator_intent_summary",
                "working_title_options",
                "retrieved_project_facts",
                "retrieved_production_constraints",
                "concept_directions",
                "creative_production_implications",
                "intentionally_open_territory",
                "creator_choices_questions",
                "governance_boundary",
            }.issubset(set(BrainstormResponse.model_fields))
        )

        self.assertTrue(
            {
                "creator_selected_or_steered_direction",
                "refined_premise",
                "hook",
                "narrative_objective",
                "emotional_objective",
                "beginning",
                "progression",
                "payoff",
                "production_implications",
                "continuity_constraint_risks",
                "unresolved_creative_decisions",
                "storyboard_readiness_recommendation",
            }.issubset(set(refinement_agent.RefineResponse.model_fields))
        )

    def test_brainstorm_output_is_non_authoritative(self) -> None:
        response = BrainstormResponse(
            stage="brainstorm",
            project_id="11111111-1111-4111-8111-111111111111",
            creator_intent_summary="A concise summary of durable creator intent.",
            working_title_options=[
                {
                    "option_id": "title-1",
                    "title": "Memory Thread",
                    "rationale": "Derived from the creator's stated intent.",
                    "recommendation_authority": "ai_recommendation",
                    "source_provenance_references": [
                        "project.initial_creative_intent"
                    ],
                },
                {
                    "option_id": "title-2",
                    "title": "Studio Echo",
                    "rationale": "Reflects the production-memory premise.",
                    "recommendation_authority": "ai_recommendation",
                    "source_provenance_references": [
                        "project.initial_creative_intent"
                    ],
                },
                {
                    "option_id": "title-3",
                    "title": "First Signal",
                    "rationale": "Keeps the title concise and unresolved.",
                    "recommendation_authority": "ai_recommendation",
                    "source_provenance_references": [
                        "project.initial_creative_intent"
                    ],
                },
            ],
            retrieved_project_facts=["Working title not yet selected."],
            retrieved_production_constraints=["No approved constraints were found."],
            concept_directions=["Direction one.", "Direction two."],
            creative_production_implications=[
                "Implication one.",
                "Implication two.",
            ],
            intentionally_open_territory=["Open choice one.", "Open choice two."],
            creator_choices_questions=["Question one?", "Question two?"],
            governance_boundary=RECOMMENDATION_GOVERNANCE_BOUNDARY,
            non_fabrication_statement=refinement_agent.NON_FABRICATION_STATEMENT,
        )

        self.assertIn("non-authoritative recommendation", response.governance_boundary)
        self.assertNotIn("approved canon", response.governance_boundary)
        self.assertTrue(response.working_title_options)
        for option in response.working_title_options:
            self.assertEqual(option.recommendation_authority, "ai_recommendation")

    def test_agent_context_retrieval_uses_mcp_not_direct_clickhouse(self) -> None:
        source = inspect.getsource(refinement_agent)

        self.assertIn("retrieve_project_memory_bundle", source)
        self.assertIn("retrieve_stage_memory", source)
        self.assertNotIn("clickhouse_connect", source)
        self.assertNotIn("ClickHouseProjectPersistence", source)
        self.assertNotIn("decision_log.insert", source)
        self.assertNotIn("assets.insert", source)

    def test_runtime_modules_do_not_hard_code_project_values(self) -> None:
        runtime_source = "\n".join(
            [
                inspect.getsource(refinement_agent),
                inspect.getsource(project_service),
            ]
        )

        self.assertNotRegex(
            runtime_source,
            re.compile(
                r"[0-9a-fA-F]{8}-"
                r"[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{12}"
            ),
        )
        self.assertNotIn("Creator Project", runtime_source)
        self.assertNotIn("decision_log.insert", runtime_source)
        self.assertNotIn("assets.insert", runtime_source)

    def test_project_id_is_parameterized_in_mcp_query(self) -> None:
        first_id = "11111111-1111-4111-8111-111111111111"
        second_id = "22222222-2222-4222-8222-222222222222"

        first_query = _project_query(first_id, "test_db")
        second_query = _project_query(second_id, "test_db")

        self.assertIn(first_id, first_query)
        self.assertIn("initial_creative_intent", first_query)
        self.assertNotIn(second_id, first_query)
        self.assertIn(second_id, second_query)
        self.assertNotIn(first_id, second_query)

    def test_storyboard_candidate_supports_multiple_ordered_shots(self) -> None:
        first_panel = StoryboardPanel(
            panel_shot_number=1,
            duration="0:00-0:05",
            story_purpose="Establish the premise.",
            visual_description="Opening image.",
            visual_treatment="Naturalistic.",
            composition="Centered subject.",
            camera_framing="Wide frame.",
            lighting="Soft key light.",
            environment="Creator-defined setting.",
            image_generation_prompt="Image prompt for panel one.",
            video_generation_prompt="Video prompt for panel one.",
            dialogue="",
            voice_tts_direction="Measured voice direction.",
            sound_effects=["Room tone"],
            ambience="Quiet interior ambience.",
            music_direction="Sparse music bed.",
            editing_notes="Cut on action.",
            continuity_notes="Maintain established palette.",
            asset_requirements=["Primary background"],
            reuse_opportunities=["Reuse approved background if available."],
            production_notes="Keep unresolved facts out of the image prompt.",
        )
        second_panel = first_panel.model_copy(update={"panel_shot_number": 2})

        candidate = StoryboardCandidate(
            stage="finalize_storyboard",
            project_id="11111111-1111-4111-8111-111111111111",
            working_title="Creator Project",
            target_total_runtime="60 seconds",
            creative_narrative_objective="Clarify the production objective.",
            production_constraints_applied=["Use creator-approved visual constraints."],
            unresolved_issues=["Creator must approve the candidate."],
            approval_governance_status=STORYBOARD_GOVERNANCE_STATUS,
            panels=[first_panel, second_panel],
            non_fabrication_statement=refinement_agent.NON_FABRICATION_STATEMENT,
        )

        self.assertEqual(
            [panel.panel_shot_number for panel in candidate.panels],
            [1, 2],
        )
        self.assertEqual(
            candidate.approval_governance_status,
            STORYBOARD_GOVERNANCE_STATUS,
        )

    def test_storyboard_schema_contains_required_production_fields(self) -> None:
        fields = set(StoryboardPanel.model_fields)
        self.assertTrue(
            {
                "duration",
                "image_generation_prompt",
                "video_generation_prompt",
                "dialogue",
                "voice_tts_direction",
                "sound_effects",
                "ambience",
                "music_direction",
                "editing_notes",
                "continuity_notes",
                "asset_requirements",
                "reuse_opportunities",
                "production_notes",
            }.issubset(fields)
        )

    def test_no_non_google_ai_runtime_dependency_is_declared(self) -> None:
        with open("requirements.txt", encoding="utf-8") as handle:
            requirements = handle.read().lower()

        self.assertIn("google-adk", requirements)
        self.assertIn("google-genai", requirements)
        self.assertNotIn("openai", requirements)
        self.assertNotIn("anthropic", requirements)
        self.assertNotIn("elevenlabs", requirements)


if __name__ == "__main__":
    unittest.main()
