"""Canonical STUDIO//ONE workflow stages."""

from __future__ import annotations

from enum import Enum


class StudioOneStage(str, Enum):
    BRAINSTORM = "brainstorm"
    REFINE = "refine"
    FINALIZE_STORYBOARD = "finalize_storyboard"
    GENERATE_ASSETS = "generate_assets"
    QUALITY_CONTROL = "quality_control"
    POST_PRODUCTION = "post_production"
    PUBLISH = "publish"


CANONICAL_STAGE_IDENTIFIERS = tuple(stage.value for stage in StudioOneStage)
IMPLEMENTED_STAGE_IDENTIFIERS = (
    StudioOneStage.BRAINSTORM.value,
    StudioOneStage.REFINE.value,
    StudioOneStage.FINALIZE_STORYBOARD.value,
    StudioOneStage.GENERATE_ASSETS.value,
    StudioOneStage.QUALITY_CONTROL.value,
    StudioOneStage.POST_PRODUCTION.value,
    StudioOneStage.PUBLISH.value,
)
