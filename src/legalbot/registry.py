"""Act registry: which Acts exist, their status, and how people refer to them."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .config import DATA_DIR
from .schema import Status


@dataclass(frozen=True)
class ActInfo:
    act_id: str
    name: str
    short: str
    year: int | None
    status: Status
    aliases: tuple[str, ...] = ()
    replaces: tuple[str, ...] = ()
    replaced_by: str | None = None
    effective_from: str | None = None


class ActRegistry:
    def __init__(self, acts: Iterable[ActInfo]):
        self._acts: dict[str, ActInfo] = {a.act_id: a for a in acts}
        self._alias_to_id: dict[str, str] = {}
        for act in self._acts.values():
            for alias in {act.act_id, act.short, *act.aliases}:
                self._alias_to_id[alias.lower()] = act.act_id
        self._pattern = self._build_pattern()
        self._compiled = re.compile(self._pattern, re.IGNORECASE)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ActRegistry":
        path = Path(path) if path else DATA_DIR / "acts.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        acts = [
            ActInfo(
                act_id=act_id,
                name=spec["name"],
                short=spec.get("short", act_id.upper()),
                year=spec.get("year"),
                status=Status(spec.get("status", "in_force")),
                aliases=tuple(spec.get("aliases", [])),
                replaces=tuple(spec.get("replaces", [])),
                replaced_by=spec.get("replaced_by"),
                effective_from=spec.get("effective_from"),
            )
            for act_id, spec in raw.items()
        ]
        return cls(acts)

    def __contains__(self, act_id: str) -> bool:
        return act_id in self._acts

    def get(self, act_id: str) -> ActInfo:
        try:
            return self._acts[act_id]
        except KeyError:
            raise KeyError(f"Unknown act '{act_id}'. Known acts: {', '.join(sorted(self._acts))}") from None

    def all(self) -> list[ActInfo]:
        return list(self._acts.values())

    def shorts(self) -> list[str]:
        return [a.short for a in self._acts.values()]

    def resolve(self, token: str) -> str | None:
        """Map an alias / short name / id to an act_id."""
        return self._alias_to_id.get(token.strip().lower())

    @property
    def alias_pattern(self) -> str:
        """Regex alternation (no capture group) matching any act alias."""
        return self._pattern

    def _build_pattern(self) -> str:
        aliases = sorted(self._alias_to_id, key=len, reverse=True)
        parts = [re.escape(a).replace(r"\ ", r"\s+") for a in aliases]
        return r"(?<![A-Za-z0-9])(?:" + "|".join(parts) + r")(?![A-Za-z0-9])"

    def find_in_text(self, text: str) -> list[str]:
        """Act ids mentioned in text, in order of first appearance."""
        seen: list[str] = []
        for m in self._compiled.finditer(text):
            act_id = self.resolve(re.sub(r"\s+", " ", m.group(0)))
            if act_id and act_id not in seen:
                seen.append(act_id)
        return seen
