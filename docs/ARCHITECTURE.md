# STUDIO//ONE MVP Architecture

This document captures the approved MVP architecture for STUDIO//ONE. It is governed by `docs/PROJECT_ALIGNMENT.md` and is scoped to the smallest production architecture that can deliver the complete hackathon vertical slice.

STUDIO//ONE is a human-governed production-intelligence system for independent creators and creator-scale teams. Awesomeverse is a case study used to validate the workflow; it is not the product architecture.

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

`web UI`: Provides the creator-facing product workflow: submit a production request or Scene Packet, inspect retrieved context, review asset reuse opportunities, inspect QC findings, review Gemini recommendations, and make an explicit human decision.

`FastAPI application`: Hosts the web app and workflow API. It coordinates request handling, validation, persistence calls, governance checks, and response formatting.

`workflow service`: Owns the end-to-end MVP flow from creator request to pending recommendation, human decision, controlled production-state update, and knowledge capture.

`Google ADK / Gemini reasoning layer`: Performs reasoning and recommendation synthesis. It may retrieve, analyze, compare, detect, explain, recommend, prepare proposed changes, and identify quality or continuity issues. It must not approve its own recommendations or write approved production state.

`official mcp-clickhouse runtime`: Provides the required agent-facing retrieval path into ClickHouse production memory. It should be the demonstrated path for meaningful production-context retrieval.

`deterministic production QC`: Performs rule-based checks that do not require model reasoning, such as missing metadata, missing source references, incompatible status, stale version references, incomplete provenance, duplicate or reusable asset candidates, and technical suitability checks.

`Gemini reasoning-based QC`: Evaluates creative/story fit, continuity implications, visual consistency, production-readiness concerns, and evidence-backed risk explanations using MCP-retrieved context.

`provenance service`: Normalizes authority level, authoritative source/reference, source version, evidence reference, approval/status state, Gemini model metadata, and human reviewer identity where applicable.

`governance service`: Enforces the boundary between findings, recommendations, approvals, authoritative production state, and audit history.

`direct ClickHouse persistence client`: Performs application-owned writes to `review_queue`, `decision_log`, and approved controlled production-state records. It is not an agent retrieval substitute.

`Google Secret Manager`: Stores runtime secrets such as ClickHouse credentials, MCP credentials, and Google/Gemini configuration values that must never be committed to Git.

## Authority And Data Ownership Model

STUDIO//ONE follows "One Fact. One Home."

Every finding, recommendation, and production-state update must identify its authoritative source/reference and source version where applicable. The system must preserve the difference between an external authoritative source document, ClickHouse production state, an AI finding, a recommendation, a human approval, and an audit record.

`projects`: Stores approved production state and references to authoritative sources for project-level context, creative intent, constraints, status, and source/version metadata. It does not automatically replace external canon, production bibles, Scene Packets, or other authoritative source documents.

`assets`: Stores approved production state and references to authoritative sources for assets, including identity, status, type, version, provenance, technical metadata, reuse relationships, and production suitability. It does not automatically replace the original asset source, external asset registry, production bible, or other canonical document.

`review_queue`: Stores pending, approved, rejected, or revision-requested recommendations and findings. It is not authoritative production state. It is the human-review work surface.

`decision_log`: Stores append-only audit history of explicit human decisions. It records who decided, what was decided, why, when, what evidence was used, and what production-state records were affected. It is not itself the authoritative production state.

`provenance/evidence`: Records how a finding or recommendation was derived, including authority level, authoritative source/reference, source version, evidence reference, approval/status state, Gemini model metadata, and human reviewer identity where applicable.

Wherever practical, production history should be append-only or versioned. Use explicit supersession of prior records instead of destructive replacement so the system preserves production history, source lineage, and decision traceability.

## MVP Runtime Sequence

1. Creator opens the hosted STUDIO//ONE web UI.
2. Creator submits a production request or Scene Packet.
3. FastAPI validates the request and starts a workflow run.
4. The workflow service invokes the Google ADK / Gemini reasoning layer.
5. Gemini retrieves production memory through the official `mcp-clickhouse` runtime.
6. ClickHouse MCP returns relevant project state, asset records, source references, source versions, reuse relationships, prior review outcomes, decision history, provenance, and QC history.
7. Deterministic production QC checks the retrieved context for missing metadata, source/version gaps, reuse candidates, incomplete provenance, technical suitability issues, and production-readiness gaps.
8. Gemini reasoning-based QC evaluates creative/story fit, continuity, visual consistency, production risks, reuse strategy, and evidence-backed recommendations.
9. The workflow service validates that recommendations and findings are distinct from approvals and include required provenance/evidence.
10. Direct ClickHouse persistence writes a pending `review_queue` record.
11. No `decision_log` entry is written and no consequential production-state change is applied during recommendation creation.
12. The web UI shows the pending recommendation, QC findings, reuse analysis, evidence references, provenance, and proposed controlled state change.
13. A human reviewer explicitly approves, rejects, or requests revision.
14. On approval, direct ClickHouse persistence writes an auditable `decision_log` entry, updates review status, and applies the controlled production-state update to `projects` and/or `assets`.
15. On rejection or revision request, direct ClickHouse persistence updates review status and writes the appropriate audit event without applying the proposed production-state change.
16. Knowledge capture is preserved through updated production state, provenance links, review status, and decision audit history.

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

## Milestone 1 Objective

Prove the governed runtime path from MCP-based production-memory retrieval to pending Gemini recommendation, without allowing AI output to become approved production state.

## Milestone 1 Acceptance Criteria

- A local or hosted FastAPI workflow accepts a production request or Scene Packet.
- Google ADK / Gemini runs as the reasoning layer.
- Gemini retrieves meaningful production context through official `mcp-clickhouse`.
- Retrieved context includes project and asset production-memory data with source/reference and version information where available.
- The workflow produces asset audit, reuse-before-creation analysis, deterministic QC findings, Gemini reasoning-based QC, and an evidence-backed recommendation.
- The recommendation is written to `review_queue` with pending status.
- No `decision_log` entry is created during recommendation generation.
- No consequential production-state update is applied without explicit human approval.
- Provenance includes authority level, authoritative source/reference, source version where applicable, evidence reference, approval/status state, Gemini model metadata, and human reviewer identity where applicable.

## Known Unresolved Technical Decisions

- Exact existing ClickHouse table columns and whether schema changes or companion tables are allowed for provenance, versions, reuse relationships, and QC findings.
- Exact official `mcp-clickhouse` runtime invocation pattern and how it is wired into Google ADK.
- Whether the MCP runtime can and should use read-only ClickHouse credentials.
- Google Cloud hosting target for the demo, with Cloud Run as the presumed default.
- Reviewer identity approach for the demo: typed reviewer identity, Google authentication, or Google Cloud IAP.
- Seed production-memory dataset that validates the workflow for independent creators generally while using Awesomeverse only as a case study.
- Whether approved production-state updates should use append-only version rows, explicit supersession columns, or ClickHouse mutations.
- How much source-document storage is in scope versus storing references to external canon, production bibles, Scene Packets, and asset systems.
- Minimal UI implementation approach for a coherent hosted product experience without overbuilding.

Implementation may begin only after this architecture is reviewed against PROJECT_ALIGNMENT.md and hackathon compliance requirements.
