# STUDIO//ONE Project Alignment

## Official Product Identity

Official product name: STUDIO//ONE

North Star: "Your vision doesn't have to be the size of your team."

Positioning: "Studio-scale production intelligence for independent creators."

Product philosophy: "The studio remembers. The agent reasons. You direct."

## Core Problem

Generative AI has increased the amount of content an individual creator can produce, but it has not given independent creators the operational infrastructure of a studio.

As projects grow, creators must personally coordinate production state, assets, versions, continuity, quality control, provenance, approvals, decisions, and accumulated production knowledge.

## Product Purpose

STUDIO//ONE compresses useful studio-scale production discipline into a human-governed production-intelligence system for independent creators and creator-scale teams.

It helps a creator manage more production complexity without surrendering creative authority.

## Positioning Boundary

STUDIO//ONE is not primarily a content generator, autonomous filmmaker, or generic chatbot.

Its central innovation is operational leverage: production memory, workflow intelligence, continuity, asset reuse, content and asset quality control, provenance, review, and institutional learning.

## Production Principles

The hackathon implementation adapts these principles from the production workflow:

- One Fact. One Home.
- Search and reuse before creating.
- Preserve before replacing.
- Story and creative intent remain authoritative.
- AI assists production; humans approve production.
- Every important recommendation should be traceable to evidence.
- Every production should leave behind reusable knowledge.
- Content and asset quality control are mandatory parts of the production pipeline.

## Creator Workflow

STUDIO//ONE collaborates with the creator from ideation onward. The creator does not begin by submitting a completed Scene Packet.

The authoritative user-facing workflow is exactly:

```text
BRAINSTORM → REFINE → FINALIZE STORYBOARD → GENERATE ASSETS → QUALITY CONTROL → POST PRODUCTION → PUBLISH
```

`BRAINSTORM`: The creator provides initial creative intent. Gemini collaborates on ideas using MCP-retrieved production memory. Outputs remain recommendations, not canon.

`REFINE`: The creator selects or steers ideas. Gemini uses accumulated production memory and human direction. The concept becomes more production-ready without becoming approved canon automatically.

`FINALIZE STORYBOARD`: STUDIO//ONE produces the complete production storyboard for creator approval. This is the main production handoff artifact and includes visual direction, image prompts, video prompts, dialogue, voice/TTS direction, SFX, ambience, music, timing, editing notes, continuity notes, asset requirements, reuse notes, and production guidance.

`GENERATE ASSETS`: STUDIO//ONE starts only from a creator-approved storyboard, extracts asset requirements, searches production memory for reuse opportunities, recommends reuse before new creation, identifies missing assets, and prepares production-ready image prompts, video prompts, dialogue direction, voice/TTS direction, and generation handoff packages. STUDIO//ONE does not generate images, video, or audio; the creator selects and operates any external generation tools.

`QUALITY CONTROL`: STUDIO//ONE evaluates externally generated or reused assets against the storyboard, continuity, production constraints, technical suitability, provenance, and quality. Failed assets loop back to `GENERATE ASSETS` for revised prompts, revised handoff instructions, or creator-operated regeneration.

`POST PRODUCTION`: STUDIO//ONE prepares the editing package: approved storyboard, shot order, timing, dialogue, SFX, ambience, music direction, transitions, and editorial notes. STUDIO//ONE does not perform final editing; the creator edits externally.

`PUBLISH`: STUDIO//ONE prepares creator-approved options for title, SEO, caption, description, hashtags, and platform-specific copy. STUDIO//ONE does not publish directly; the creator publishes manually.

Scene Packets, storyboard plans, asset plans, QC records, and decision records are structured artifacts and state created and evolved inside this workflow.

Knowledge capture, provenance, production memory, human governance, and audit history are cross-cutting system behaviors, not additional user-facing workflow stages.

## Ownership Boundaries

STUDIO//ONE provides collaborative ideation, concept refinement, production-memory retrieval through official `mcp-clickhouse`, storyboard / production-board generation, scene-level production planning, image prompts, video-generation prompts, dialogue, voice/TTS direction, sound effects cues, ambience, music direction, pacing, editing notes, asset requirements, asset audit / reuse-before-create analysis, generation handoff packages, content and asset QC, revision / regeneration recommendations for creator-operated tools, the `POST PRODUCTION` editing package, `PUBLISH` copy options for creator approval, provenance, governance, and knowledge capture.

`PUBLISH` options may include SEO options, title options, captions, descriptions, hashtags, and platform-specific copy.

STUDIO//ONE does not perform final video editing, generate images, generate video, synthesize dialogue audio, call TTS providers, choose the creator's external generation platform, operate the creator's external editing software, directly publish to social or online platforms, autonomously approve final creative decisions, autonomously establish canon, or call prohibited non-Google AI APIs in the submitted hackathon runtime.

The system connects production knowledge and decisions across tools; it does not replace every creative-production tool.

## External Tool Handoffs

The STUDIO//ONE workflow may include manual external creator handoffs inside the appropriate workflow stage:

- STUDIO//ONE prepares image prompts, asset requirements, and handoff notes.
- Creator uses approved handoff packages in external tools when needed.
- Creator brings resulting assets back for QC, provenance review, and knowledge capture.
- During `POST PRODUCTION`, creator performs editing manually.
- During `PUBLISH`, creator publishes manually.

STUDIO//ONE prepares production intelligence and generation packages; the creator selects and operates generation tools. External creative tools are manual creator handoffs, not STUDIO//ONE runtime AI integrations. STUDIO//ONE's submitted AI runtime remains Google-only and does not perform image generation, video generation, or dialogue-audio synthesis.

## Asset-State Semantics

STUDIO//ONE must keep these asset-state concepts distinct:

- `asset_requirement`: a storyboard-derived need for an asset.
- `reusable_existing_asset`: an existing production-memory asset that may satisfy a requirement.
- `generation_prompt`: production-ready instructions for creator-operated generation; this is not an asset.
- `externally_generated_asset`: an asset generated or prepared outside STUDIO//ONE and brought back for review.
- `qc_approved_asset`: an asset that passed STUDIO//ONE quality control and any required human approval.

A generated prompt is not an asset. An asset must not enter the approved asset library merely because a prompt exists.

## Human Authority

AI may retrieve, analyze, compare, detect, explain, recommend, prepare proposed changes, and identify quality and continuity issues.

AI must not silently establish authoritative creative truth, approve its own consequential recommendations, overwrite approved production state, or replace explicit human approval.

## Hackathon Target

Target event: Agentic Cinema: The Blockbuster Hackathon, ClickHouse partner track.

Required submitted runtime:

- Gemini
- Google Cloud
- Google ADK or applicable Google agent platform
- ClickHouse
- Official mcp-clickhouse runtime integration
- Hosted functional application

Do not introduce non-Google AI models or APIs into the submitted runtime.

## ClickHouse Role

ClickHouse is the production-memory and operational-intelligence layer, not decorative storage.

The agent must actively retrieve meaningful production context through the official ClickHouse MCP runtime path.

## Core MVP Vertical Slice

The MVP vertical slice is:

BRAINSTORM → REFINE → FINALIZE STORYBOARD → GENERATE ASSETS → QUALITY CONTROL → POST PRODUCTION → PUBLISH

For the three-minute hackathon demo, STUDIO//ONE should show a vertical slice inside this real lifecycle rather than attempting to demonstrate the full production lifecycle end to end.

## MVP Quality-Control Scope

The MVP should include checks relevant to the supplied production context, such as:

- Creative and story fit
- Continuity
- Visual consistency
- Technical suitability
- Missing requirements
- Reuse and documentation status
- Provenance
- Other production-readiness concerns

Findings are recommendations requiring human review.

## Initial Production-Memory Concepts

Initial production-memory concepts include:

- Projects
- Episode and production ideas
- Assets
- Storyboard and production plans
- Asset plans
- Review queue
- Decision history
- Provenance and evidence
- Approval and status state
- Source and version information
- Reuse relationships
- QC findings
- QC records

## Competition Design Goal

Demonstrate a complete coherent product workflow rather than a collection of AI features.

## Three-Minute Demo Thesis

Show one creator starting with an episode or production idea.

The agent retrieves production memory through ClickHouse MCP, supports `BRAINSTORM` and `REFINE`, produces a `FINALIZE STORYBOARD` candidate for creator approval, asks the creator for any consequential decision, and records resulting production knowledge through cross-cutting production memory and audit behavior.

## Completed Runtime Checkpoint

The following competition runtime path has been proven locally:

`Creator -> Google ADK/Gemini -> official mcp-clickhouse -> ClickHouse production memory -> STUDIO//ONE refinement`

The current proof uses `google.adk` `LlmAgent`, `Runner`, a constrained `FunctionTool`, Gemini `gemini-2.5-flash` on Vertex AI `us-central1`, and official `mcp-clickhouse` over stdio. Production-memory retrieval occurs through MCP, with no direct ClickHouse reads for agent context and no ClickHouse writes during the refinement proof.

## Judging Alignment

- Technological Implementation: meaningful Gemini, Google Cloud, and ClickHouse MCP runtime integration.
- Design: coherent creator-facing production workflow, not merely a technical proof of concept.
- Potential Impact: increase the production complexity small teams can manage while reducing rework, duplicated creation, continuity failures, and lost knowledge.
- Quality of Idea: operational intelligence for AI-assisted creative production rather than another content-generation tool.

## Scope Guardrails

Do not turn the MVP into:

- Autonomous movie generation
- A complete DAM
- A full project-management suite
- An autonomous publishing system
- A giant multi-agent swarm
- A replacement for the entire studio workflow

## Feature Admission Test

A proposed MVP feature should satisfy all three:

1. Does it increase the production complexity a small creative team can successfully manage?
2. Does it implement a meaningful part of the real production workflow, especially production memory, asset reuse, continuity, QC, provenance, or human governance?
3. Does it strengthen the competition submission through demonstrable Gemini, Google Cloud, and ClickHouse functionality?

## Long-Term Vision

STUDIO//ONE should eventually make increasing portions of a disciplined creative-production operating system machine-executable while keeping creative authority with the creator.

This document governs hackathon implementation decisions. When an implementation choice conflicts with this product alignment, stop and resolve the conflict before proceeding.
