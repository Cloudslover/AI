"""Authorization policies for turning research plans into trade candidates.

The rule engine deliberately generates every setup it can observe.  A policy is
applied *after* generation and calibration, at the decision boundary.  This
keeps research/learning broad while allowing the live desk to authorize one
setup family at a time.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Protocol

from .rules import Plan


class PlanAuthorizationPolicy(Protocol):
    """A pure policy that marks which generated plans may reach the desk."""

    name: str

    def authorize(self, plans: Iterable[Plan]) -> tuple[Plan, ...]:
        ...


@dataclass(frozen=True)
class SetupFamilyPolicy:
    """Authorize a fixed setup family; ``allowed_types=None`` means radar mode."""

    allowed_types: frozenset[str] | None = None
    name: str = "all"

    @classmethod
    def from_types(cls, allowed_types: set[str] | None,
                   name: str = "configured_setup_family") -> "SetupFamilyPolicy":
        return cls(None if allowed_types is None else frozenset(allowed_types), name)

    def authorize(self, plans: Iterable[Plan]) -> tuple[Plan, ...]:
        out: list[Plan] = []
        for plan in plans:
            allowed = self.allowed_types is None or plan.type in self.allowed_types
            reason = (f"authorized by {self.name}" if allowed else
                      f"research-only: {plan.type} is outside {self.name}")
            out.append(replace(plan, primary=allowed, authorization_reason=reason))
        return tuple(out)


@dataclass(frozen=True)
class AllowAllPolicy(SetupFamilyPolicy):
    allowed_types: frozenset[str] | None = None
    name: str = "all"
