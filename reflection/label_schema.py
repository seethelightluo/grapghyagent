"""Reflection label schema."""
from __future__ import annotations

from ..core.enums import REFLECTION_LABELS

POSITIVE_LABELS = {"useful", "critical"}
NEGATIVE_LABELS = {"unused", "risky", "misleading", "insufficient"}

__all__ = ["NEGATIVE_LABELS", "POSITIVE_LABELS", "REFLECTION_LABELS"]
