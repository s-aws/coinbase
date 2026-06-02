"""Post-fill retreat policy for hidden same-side stealth orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from calculation.formatter import safe_float
from core.enums import PostFillRetreatScope


@dataclass(frozen=True)
class PostFillRetreatPolicy:
    """Normalized opt-in policy for same-side hidden-order retreat."""

    enabled: bool = False
    scope: PostFillRetreatScope = PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE
    retreat_ticks: int = 1
    inherit_to_follow_ups: bool = True

    @staticmethod
    def _read_post_fill_retreat_policy_field(
        config: Dict[str, Any],
        field_name: str,
        default: Any = None,
    ) -> Any:
        if field_name in config:
            return config[field_name]
        return default

    @classmethod
    def disabled(cls) -> "PostFillRetreatPolicy":
        return cls(enabled=False)

    @classmethod
    def from_post_fill_retreat_policy_dict(
        cls,
        raw: Optional[Dict[str, Any]],
    ) -> "PostFillRetreatPolicy":
        config = dict(raw or {})
        field = cls._read_post_fill_retreat_policy_field
        if not bool(field(config, "enabled")):
            return cls.disabled()

        scope_raw = str(
            field(config, "scope") or PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE.value
        ).strip().lower()
        try:
            scope = PostFillRetreatScope(scope_raw)
        except ValueError:
            scope = PostFillRetreatScope.SAME_PRODUCT_SAME_SIDE

        retreat_ticks = max(
            int(safe_float(field(config, "retreat_ticks"), default=1.0)),
            1,
        )

        return cls(
            enabled=True,
            scope=scope,
            retreat_ticks=retreat_ticks,
            inherit_to_follow_ups=bool(field(config, "inherit_to_follow_ups", True)),
        )

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "PostFillRetreatPolicy":
        """Backward-compatible alias for older callers."""
        return cls.from_post_fill_retreat_policy_dict(raw)

    def to_post_fill_retreat_policy_dict(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "scope": self.scope.value,
            "retreat_ticks": self.retreat_ticks,
            "inherit_to_follow_ups": self.inherit_to_follow_ups,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Backward-compatible alias for older callers."""
        return self.to_post_fill_retreat_policy_dict()
