"""Run the STUDIO//ONE REFINE stage agent."""

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

from studio_one.agents.refinement_agent import (  # noqa: E402
    run_refine_agent,
    sanitize_runtime_report,
)


warnings.filterwarnings(
    "ignore",
    message=r"\[EXPERIMENTAL\] feature FeatureName\.JSON_SCHEMA_FOR_FUNC_DECL.*",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run project-scoped STUDIO//ONE REFINE through ADK/Gemini.",
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "creator_direction",
        nargs="+",
        help="Explicit creator direction required for REFINE.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    report = await run_refine_agent(
        creator_direction=" ".join(args.creator_direction).strip(),
        project_id=args.project_id,
    )
    print(json.dumps(sanitize_runtime_report(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    anyio.run(main)
