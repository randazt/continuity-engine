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

## Case Study Relationship

Awesomeverse is the real-world case study, not the product.

The production methodology developed while creating Awesomeverse informs STUDIO//ONE, but the application must remain useful and understandable for filmmakers, designers, developers, content creators, animation teams, and small creative studios generally.

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

Production request / Scene Packet -> authoritative context -> ClickHouse production-memory retrieval through MCP -> asset audit and reuse analysis -> continuity analysis -> content and asset QC -> evidence-backed Gemini recommendation -> explicit human review -> decision/audit record -> controlled production-state update -> knowledge capture.

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
- Assets
- Review queue
- Decision history
- Provenance and evidence
- Approval and status state
- Source and version information
- Reuse relationships
- QC findings

## Competition Design Goal

Demonstrate a complete coherent product workflow rather than a collection of AI features.

## Three-Minute Demo Thesis

Show one creator giving STUDIO//ONE a real production objective.

The agent retrieves production memory through ClickHouse MCP, identifies existing and reusable assets and production risks, performs continuity and QC reasoning, produces evidence-backed recommendations, asks the creator for a consequential decision, and records the resulting production knowledge.

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
