"""Old-code <-> new-code section mapping (IPC -> BNS today; CrPC -> BNSS and IEA -> BSA later).

Older case law and most people's habits still use IPC numbers, so queries like
"IPC 420" must land on the BNS provision. The shipped CSV is a *starter* set and every row
is marked verified=false: check it against the government's official comparison tables
before relying on it, then flip the flag.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR


@dataclass(frozen=True)
class Mapping:
    old_act: str
    old_section: str
    new_act: str
    new_section: str
    new_ref: str
    note: str
    verified: bool


class Concordance:
    def __init__(self, rows: list[Mapping]):
        self.rows = rows
        self._forward: dict[tuple[str, str], list[Mapping]] = {}
        self._backward: dict[tuple[str, str], list[Mapping]] = {}
        for m in rows:
            self._forward.setdefault((m.old_act, m.old_section.upper()), []).append(m)
            self._backward.setdefault((m.new_act, m.new_section.upper()), []).append(m)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Concordance":
        path = Path(path) if path else DATA_DIR / "ipc_to_bns.csv"
        with path.open(encoding="utf-8", newline="") as f:
            rows = [
                Mapping(
                    old_act=r["old_act"].strip(),
                    old_section=r["old_section"].strip(),
                    new_act=r["new_act"].strip(),
                    new_section=r["new_section"].strip(),
                    new_ref=(r.get("new_ref") or r["new_section"]).strip(),
                    note=(r.get("note") or "").strip(),
                    verified=(r.get("verified") or "").strip().lower() == "true",
                )
                for r in csv.DictReader(f)
            ]
        return cls(rows)

    def forward(self, act_id: str, section: str) -> list[Mapping]:
        """Old section -> its current equivalent(s)."""
        return self._forward.get((act_id, section.upper()), [])

    def backward(self, act_id: str, section: str) -> list[Mapping]:
        """Current section -> the old section(s) it replaced."""
        return self._backward.get((act_id, section.upper()), [])
