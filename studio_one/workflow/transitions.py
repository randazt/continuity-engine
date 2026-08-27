"""Creator-controlled workflow transition rules."""

from __future__ import annotations

from studio_one.workflow.stages import StudioOneStage


CREATOR_CONTROLLED_TRANSITIONS = {
    StudioOneStage.BRAINSTORM: StudioOneStage.REFINE,
    StudioOneStage.REFINE: StudioOneStage.FINALIZE_STORYBOARD,
}


def require_creator_action_transition(
    current_stage: StudioOneStage,
    requested_stage: StudioOneStage,
    creator_action: str | None,
) -> None:
    """Validate that a supported stage transition has explicit creator action."""
    expected_stage = CREATOR_CONTROLLED_TRANSITIONS.get(current_stage)
    if expected_stage != requested_stage:
        raise ValueError(
            f"Unsupported workflow transition: {current_stage.value} "
            f"to {requested_stage.value}"
        )

    if not creator_action or not creator_action.strip():
        raise ValueError(
            f"Creator action is required for {current_stage.value} "
            f"to {requested_stage.value}"
        )
