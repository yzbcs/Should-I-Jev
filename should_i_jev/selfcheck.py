"""Self-audit: ask Jev (or its offline stand-in) which call sites Jev should take."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .audit import Audit
from .code_scan import CodeScan
from .jev_client import ask_choice

QUESTION = "Is this LLM call a typed decision task (classify / route / rate / verify) that should move to Jev?"
OPTIONS = ["yes", "no"]


@dataclass
class SelfcheckRow:
    origin: str
    heuristic: str          # verdict label key
    choice: str
    p: Optional[float]
    agrees: bool


@dataclass
class SelfcheckResult:
    rows: List[SelfcheckRow] = field(default_factory=list)
    mock: bool = True
    errors: int = 0

    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def agreement(self) -> float:
        if not self.rows:
            return 0.0
        return sum(1 for r in self.rows if r.agrees) / len(self.rows)


def _ask(state: Dict, base_url: Optional[str], api_key: Optional[str]) -> Optional[Dict]:
    try:
        return ask_choice(QUESTION, OPTIONS, state=state, base_url=base_url, api_key=api_key)
    except Exception:
        return None


def run_selfcheck(
    scan: Optional[CodeScan] = None,
    audit: Optional[Audit] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    limit: int = 25,
) -> SelfcheckResult:
    result = SelfcheckResult()

    targets: List[Dict] = []
    if scan is not None and scan.findings:
        for f in sorted(scan.findings, key=lambda f: -f.detail.score)[:limit]:
            targets.append(
                {
                    "origin": f"{f.path}:{f.line}",
                    "prompt": f.prompt_excerpt,
                    "score": f.detail.score,
                    "verdict": f.detail.verdict,
                    "kind": "code site",
                }
            )
    elif audit is not None:
        for call, detail in audit.top_candidates(limit):
            targets.append(
                {
                    "origin": call.source,
                    "prompt": call.prompt_excerpt,
                    "score": detail.score,
                    "verdict": detail.verdict,
                    "kind": "log call",
                }
            )

    for t in targets:
        answer = _ask(
            {"prompt": t["prompt"], "score": t["score"], "site": t["kind"]},
            base_url,
            api_key,
        )
        if answer is None:
            result.errors += 1
            continue
        positive = t["verdict"] in ("likely", "maybe")
        result.rows.append(
            SelfcheckRow(
                origin=t["origin"],
                heuristic=t["verdict"],
                choice=answer["choice"],
                p=answer["p"],
                agrees=(answer["choice"] == "yes") == positive,
            )
        )
        result.mock = result.mock and answer.get("mock", False)
    return result
