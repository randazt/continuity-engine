# STUDIO//ONE MVP Architecture

This document captures the approved MVP architecture for STUDIO//ONE. It is governed by `docs/PROJECT_ALIGNMENT.md` and is scoped to the smallest production architecture that can deliver the complete hackathon vertical slice.

STUDIO//ONE is a human-governed production-intelligence system for independent creators and creator-scale teams.

## System Diagram

```text
Creator browser
  |
  v
Hosted STUDIO//ONE web UI
  |
  v
FastAPI application on Google Cloud
  |
  +--> Workflow service
  |      |
  |      +--> Deterministic production QC
  |      |
  |      +--> Google ADK / Gemini reasoning layer
  |      |      |
  |      |      v
  |      |   official mcp-clickhouse runtime
  |      |      |
  |      |      v
  |      |   ClickHouse production memory
  |      |
  |      +--> Provenance and governance validation
  |
  +--> Direct ClickHouse persistence client
  |      |
  |      v
  |   review_queue, decision_log, controlled production-state writes
  |
  +--> Google Secret Manager
```

The official `mcp-clickhouse` integration is a mandatory runtime retrieval path for the agent and the competition demo. Direct ClickHouse access may be used for controlled application persistence, but it must not substitute for MCP-based agent retrieval.

## Component Responsibilities

`web UI`: Provides the creator-facing seven-stage workflow: `BRAINSTORM`, `REFINE`, `FINALIZE STORYBOARD`, `GENERATE ASSETS`, `QUALITY CONTROL`, `POST PRODUCTION`, and `PUBLISH`. It also lets the creator inspect retrieved production memory, review Gemini recommendations, and make explicit human decisions when consequential production-state changes are proposed.

`FastAPI application`: Hosts the web app and workflow API. It coordinates request handling, validation, persistence calls, governance checks, and response formatting.

`workflow service`: Owns the end-to-end seven-stage workflow from `BRAINSTORM` through `PUBLISH`, plus cross-cutting provenance, governance, controlled production-state updates, audit history, and production-memory capture.

`Google ADK / Gemini reasoning layer`: Performs reasoning and recommendation synthesis. It may retrieve, analyze, compare, detect, explain, recommend, prepare proposed changes, and identify quality or continuity issues. It must not approve its own recommendations or write approved production state.

`official mcp-clickhouse runtime`: Provides the required agent-facing retrieval path into ClickHouse production memory. It should be the demonstrated path for meaningful production-context retrieval.

`deterministic production QC`: Performs rule-based checks that do not require model reasoning, such as missing metadata, missing source references, incompatible status, stale version references, incomplete provenance, duplicate or reusable asset candidates, technical suitability checks, missing handoff requirements, and asset package completeness.

`Gemini reasoning-based QC`: Evaluates creative/story fit, continuity implications, visual consistency, production-readiness concerns, prompt/handoff coherence, revision recommendations, and evidence-backed risk explanations using MCP-retrieved context.

`provenance service`: Normalizes authority level, authoritative source/reference, source version, evidence reference, approval/status state, Gemini model metadata, and human reviewer identity where applicable.

`governance service`: Enforces the boundary between findings, recommendations, approvals, authoritative production state, and audit history.

`direct ClickHouse persistence client`: Performs application-owned writes to `review_queue`, `decision_log`, and approved controlled production-state records. It is not an agent retrieval substitute.

`Google Secret Manager`: Stores runtime secrets such as ClickHouse credentials, MCP credentials, and Google/Gemini configuration values that must never be committed to Git.

## Authority And Data Ownership Model

STUDIO//ONE follows "One Fact. One Home."

Every finding, recommendation, and production-state update must identify its authoritative source/reference and source version where applicable. The system must preserve the difference between an external authoritative source document, ClickHouse production state, an AI finding, a recommendation, a human approval, and an audit record.

`projects`: Stores approved production state and references to authoritative sources for project-level context, creative intent, constraints, status, and source/version metadata. It does not automatically replace external canon, production bibles, Scene Packets, storyboard plans, asset plans, or other authoritative source documents and workflow artifacts.

`assets`: Stores approved production state and references to authoritative sources for assets, including identity, status, type, version, provenance, technical metadata, reuse relationships, and production suitability. It does not automatically replace the original asset source, external asset registry, production bible, or other canonical document.

`review_queue`: Stores pending, approved, rejected, or revision-requested recommendations and findings. It is not authoritative production state. It is the human-review work surface.

`decision_log`: Stores append-only audit history of explicit human decisions. It records who decided, what was decided, why, when, what evidence was used, and what production-state records were affected. It is not itself the authoritative production state.

`provenance/evidence`: Records how a finding or recommendation was derived, including authority level, authoritative source/reference, source version, evidence reference, approval/status state, Gemini model metadata, and human reviewer identity where applicable.

Wherever practical, production history should be append-only or versioned. Use explicit supersession of prior records instead of destructive replacement so the system preserves production history, source lineage, and decision traceability.

## MVP Runtime Sequence

The authoritative user-facing STUDIO//ONE workflow is exactly:

```text
BRAINSTORM → REFINE → FINALIZE STORYBOARD → GENERATE ASSETS → QUALITY CONTROL → POST PRODUCTION → PUBLISH
```

The creator does not start by submitting a completed Scene Packet. STUDIO//ONE collaborates from ideation onward. Scene Packets, storyboard plans, asset plans, QC records, and decision records are structured artifacts and state created and evolved inside the workflow.

1. `BRAINSTORM`: Creator provides initial creative intent. The workflow service invokes Google ADK / Gemini, Gemini retrieves relevant production memory through official `mcp-clickhouse`, and outputs remain recommendations rather than canon.
2. `REFINE`: Creator selects or steers ideas. Gemini uses MCP-retrieved production memory, accumulated project context, and human direction to make the concept more production-ready.
3. `FINALIZE STORYBOARD`: STUDIO//ONE produces the complete production storyboard for creator approval, including visual direction, image prompts, video prompts, dialogue, voice/TTS direction, SFX, ambience, music, timing, editing notes, continuity notes, asset requirements, reuse notes, and production guidance.
4. `GENERATE ASSETS`: STUDIO//ONE starts only from a creator-approved storyboard, extracts storyboard asset requirements, searches production memory for reuse opportunities, recommends reuse before new creation, identifies missing assets, and prepares production-ready image prompts, video prompts, dialogue direction, voice/TTS direction, and generation handoff packages. STUDIO//ONE does not generate images, video, or audio; the creator selects and operates any external generation tools.
5. `QUALITY CONTROL`: STUDIO//ONE evaluates externally generated or reused assets against the storyboard, continuity, production constraints, technical suitability, provenance, and quality. Failed assets loop back to `GENERATE ASSETS` for revised prompts, revised handoff instructions, or creator-operated regeneration.
6. `POST PRODUCTION`: STUDIO//ONE prepares the editing package: approved storyboard, shot order, timing, dialogue, SFX, ambience, music direction, transitions, and editorial notes. STUDIO//ONE does not perform final editing; the creator edits externally.
7. `PUBLISH`: STUDIO//ONE prepares creator-approved title, SEO, caption, description, hashtag, and platform-copy options. STUDIO//ONE does not publish directly; the creator publishes manually.

Knowledge capture, provenance, production memory, human governance, and audit history are cross-cutting system behaviors, not additional user-facing workflow stages.

Recommendations and findings remain distinct from approvals. Direct ClickHouse persistence writes pending review records and decision audit rows only when the relevant product behavior and explicit human action require it.

For the three-minute hackathon demo, STUDIO//ONE will show a vertical slice inside this real lifecycle rather than attempting to demonstrate the full production lifecycle end to end.

## External Handoff Boundary

STUDIO//ONE produces structured handoff packages, prompts, directions, notes, and QC findings. It does not generate images, generate video, synthesize dialogue audio, operate external editing software, or directly publish to social platforms.

STUDIO//ONE prepares production intelligence and generation packages; the creator selects and operates generation tools. External creative tools are manual creator handoffs, not STUDIO//ONE runtime AI integrations. The submitted runtime remains Google-only and does not perform image generation, video generation, or dialogue-audio synthesis.

The architecture treats manual external outputs as artifacts that can return to STUDIO//ONE for QC, provenance, review, and knowledge capture.

## Asset-State Semantics

STUDIO//ONE must keep asset requirements, reuse candidates, prompts, externally generated assets, and approved assets as separate states:

- `asset_requirement`: a storyboard-derived need for an asset.
- `reusable_existing_asset`: an existing production-memory asset that may satisfy a requirement.
- `generation_prompt`: production-ready instructions for creator-operated generation; this is not an asset.
- `externally_generated_asset`: an asset generated or prepared outside STUDIO//ONE and brought back for review.
- `qc_approved_asset`: an asset that passed STUDIO//ONE quality control and any required human approval.

A generated prompt is not an asset and must not create an approved `assets` record. An asset enters the approved asset library only after the appropriate intake, provenance, QC, and human-governance path.

## Proven Runtime Checkpoint

The following local checkpoint has been completed:

```text
Creator
  -> Google ADK/Gemini
  -> official mcp-clickhouse
  -> ClickHouse production memory
  -> STUDIO//ONE refinement
```

Current implementation proof:

- `google.adk` `LlmAgent`,
- `Runner`,
- constrained `FunctionTool`,
- Gemini `gemini-2.5-flash`,
- Vertex AI `us-central1`,
- official `mcp-clickhouse` over stdio,
- production-memory retrieval through MCP,
- no direct ClickHouse reads for agent context,
- no writes during the refinement proof.

## QC Layers

Deterministic production QC is application logic. It should produce structured findings for objective or schema-checkable issues:

- missing required source/reference fields,
- missing source version,
- missing or incomplete provenance,
- asset status conflicts,
- stale or incompatible production-state references,
- duplicate/reuse candidates,
- technical suitability gaps,
- missing required production fields,
- review or documentation status gaps.

Gemini reasoning-based QC uses MCP-retrieved context to produce evidence-backed recommendations for judgment-heavy concerns:

- creative and story fit,
- continuity implications,
- visual consistency,
- asset reuse tradeoffs,
- production-readiness risks,
- likely missing context,
- proposed next actions.

Human approval is a separate layer. QC findings and Gemini recommendations remain non-authoritative until a human reviewer explicitly decides.

## Governance Boundary

Human creative authority is structurally enforced:

- the agent has no direct production-state write authority,
- the agent retrieves production memory only through the required MCP path,
- recommendations are written to `review_queue` as pending by default,
- AI output cannot mark itself approved,
- consequential production-state changes require explicit human reviewer identity and action,
- `decision_log` entries are created only by human-decision handling,
- approved production-state updates are controlled application writes,
- rejected or revision-requested recommendations do not update approved production state.

The system must keep recommendations, findings, approvals, authoritative production state, and audit history as distinct concepts.

## MCP Vs Direct Persistence Boundary

ClickHouse MCP responsibilities:

- required runtime retrieval path for the agent,
- demonstrated production-memory context retrieval for the hackathon,
- read access to meaningful ClickHouse context including projects, assets, prior decisions, source/version data, reuse relationships, provenance, and QC history,
- ideally read-only credentials for agent-facing retrieval.

Direct ClickHouse persistence responsibilities:

- create `review_queue` records,
- update `review_queue` status,
- write explicit human decision records to `decision_log`,
- apply approved controlled production-state updates,
- preserve append-only/versioned history and supersession where practical.

Direct ClickHouse access must not be used to provide agent context in place of the official MCP integration.

## Current Slice Objective

Prove the governed setup and production slice: create a generic project, enter `BRAINSTORM`, allow creator direction into `REFINE`, produce a structured `FINALIZE STORYBOARD` candidate for human approval, persist explicit storyboard approval, enter `GENERATE ASSETS` only from approved storyboard production state, run governed `QUALITY CONTROL` for creator-supplied external asset candidates, prepare a request-scoped `POST PRODUCTION` editing package from approved production state, and prepare a request-scoped `PUBLISH` package for creator approval and manual posting without allowing AI output to become approved production state.

## Current Slice Acceptance Criteria

- A local or hosted workflow creates a generic project before entering the seven-stage production workflow.
- Project creation persists the creator's initial creative intent and optional production constraints without fabricating canon, approvals, decisions, assets, or constraints.
- The production flow enters `BRAINSTORM` using the persisted project context.
- Google ADK / Gemini runs as the reasoning layer.
- Gemini retrieves meaningful production context through official `mcp-clickhouse`.
- Retrieved context includes project production-memory data, initial creative intent, optional production constraints, and source/reference/version information where available.
- Creator direction can steer the transition from `BRAINSTORM` to `REFINE`.
- The workflow produces a structured `FINALIZE STORYBOARD` candidate for human approval, including the main production handoff fields.
- `GENERATE ASSETS` prepares provider-neutral asset requirements, reuse audit results, prompts, and handoff instructions from an approved storyboard.
- `QUALITY CONTROL` evaluates creator-supplied external asset candidates against exact MCP-retrieved storyboard, package, project, and asset provenance, then creates pending human-review recommendations only.
- `POST PRODUCTION` prepares provider-neutral editing instructions from approved storyboard and approved asset state. It does not edit, render, upload to editing software, publish, or store the editing package as an asset.
- `PUBLISH` prepares provider-neutral title, SEO, caption, description, hashtag, thumbnail/key-art, accessibility, and platform-copy options from approved production state plus creator-supplied final-edit context. It does not authenticate to social media, video platforms, websites, or external services; call publishing APIs; upload media; schedule posts; click publish; claim content is live; or store the package as approved production state.
- No `decision_log` entry is created during recommendation or storyboard-candidate generation.
- No asset row is created merely because a prompt or generation package exists.
- No consequential production-state update is applied without explicit human approval.
- Provenance includes authority level, authoritative source/reference, source version where applicable, evidence reference, approval/status state, Gemini model metadata, and human reviewer identity where applicable.

## Known Unresolved Technical Decisions

- Exact existing ClickHouse table columns and whether schema changes or companion tables are allowed for provenance, versions, reuse relationships, and QC findings.
- Whether the MCP runtime can and should use read-only ClickHouse credentials.
- Google Cloud hosting target for the demo, with Cloud Run as the presumed default.
- Reviewer identity approach for the demo: typed reviewer identity, Google authentication, or Google Cloud IAP.
- How to validate production-memory retrieval against user-supplied or configured production records without requiring built-in project data.
- Whether approved production-state updates should use append-only version rows, explicit supersession columns, or ClickHouse mutations.
- How much source-document storage is in scope versus storing references to external canon, production bibles, Scene Packets, and asset systems.
- Minimal UI implementation approach for a coherent hosted product experience without overbuilding.
- Whether later submission workflows need durable package/artifact persistence for `POST PRODUCTION` or `PUBLISH`; the current milestone keeps both package types request-scoped.

Further implementation should continue to be reviewed against PROJECT_ALIGNMENT.md and hackathon compliance requirements.
