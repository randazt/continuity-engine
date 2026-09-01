"""Create a STUDIO//ONE project and start BRAINSTORM."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studio_one.services.project_service import (  # noqa: E402
    CreateProjectRequest,
    build_project_service,
)


warnings.filterwarnings(
    "ignore",
    message=r"\[EXPERIMENTAL\] feature FeatureName\.JSON_SCHEMA_FOR_FUNC_DECL.*",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a generic STUDIO//ONE project, then retrieve it through "
            "official mcp-clickhouse for ADK/Gemini BRAINSTORM."
        ),
    )
    parser.add_argument("--production-constraints", default="")
    parser.add_argument(
        "--source-reference",
        default="creator_project_creation_request",
    )
    parser.add_argument("--source-version", default="")
    parser.add_argument(
        "initial_creative_intent",
        nargs="+",
        help="Creator intent to persist before starting BRAINSTORM.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service = build_project_service()
    result = await service.create_project_and_start_brainstorm(
        CreateProjectRequest(
            production_constraints=args.production_constraints,
            source_reference=args.source_reference,
            source_version=args.source_version,
            initial_creative_intent=" ".join(args.initial_creative_intent).strip(),
        )
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    anyio.run(main)
