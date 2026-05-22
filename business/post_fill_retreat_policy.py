"""Post-fill retreat policy for hidden same-side stealth orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from configuration import safe_float
from core.enums import PostFillRetreatScope


@dataclass(frozen=True)
class PostFillRetreatPolicy:
    """Normalized opt-in policy for same-side hidden-order retreat."""

    enabled: bool = False
    scope: PostFillRetreatScope = PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE
    retreat_ticks: int = 1
    inherit_to_follow_ups: bool = True

    @classmethod
    def disabled(cls) -> "PostFillRetreatPolicy":
        return cls(enabled=False)

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "PostFillRetreatPolicy":
        config = dict(raw or {})
        if not bool(config.get("enabled")):
            return cls.disabled()

        scope_raw = str(
            config.get("scope") or PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE.value
        ).strip().lower()
        try:
            scope = PostFillRetreatScope(scope_raw)
        except ValueError:
            scope = PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE

        retreat_ticks = max(
            int(safe_float(config.get("retreat_ticks"), default=1.0)),
            1,
        )

        return cls(
            enabled=True,
            scope=scope,
            retreat_ticks=retreat_ticks,
            inherit_to_follow_ups=bool(config.get("inherit_to_follow_ups", True)),
        )

    def to_dict(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "scope": self.scope.value,
            "retreat_ticks": self.retreat_ticks,
            "inherit_to_follow_ups": self.inherit_to_follow_ups,
        }
