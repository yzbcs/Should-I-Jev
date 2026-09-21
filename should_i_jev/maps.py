"""Build JEV map sketches — shared by log audits and code scans.

A "map" is one cluster of decision-shaped calls with the same role and the
same leading question template, distilled into a typed-question sketch
(Choice with observed options / Score with observed range).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_BOOL_WORDS = {"yes", "no", "true", "false"}
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "of", "for", "to", "in", "on",
    "as", "is", "are", "and", "or", "from", "with", "into", "by", "at", "be",
}

_ROLE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\brout|\bintent\b", re.I), "Router"),
    (re.compile(r"classif|categor", re.I), "Classifier"),
    (re.compile(r"sentiment", re.I), "SentimentTrier"),
    (re.compile(r"\bspam\b", re.I), "SpamFilter"),
    (re.compile(r"toxic|moderat", re.I), "Moderator"),
    (re.compile(r"\brat(?:e|ing)|\bscor(?:e|ing)|prioriti", re.I), "Rater"),
    (re.compile(r"\bjudg|evaluat", re.I), "Judge"),
    (re.compile(r"\bextract", re.I), "Extractor"),
    (re.compile(r"\blabel|\btag(?:s|ging)?\b", re.I), "Tagger"),
    (re.compile(r"\bfilter|duplicate", re.I), "Filter"),
    (re.compile(r"\bverif|\bvalidat|\bcheck", re.I), "Verifier"),
    (re.compile(r"triage", re.I), "TriageSorter"),
]


@dataclass
class MapItem:
    prompt: str
    output: str
    score: float
    weight: int = 1
    origin: str = ""


@dataclass
class JevMap:
    role: str
    template: str
    kind: str                     # "Choice" | "Score"
    calls: int
    score_range: Tuple[float, float]
    options: Optional[list] = None
    note: Optional[str] = None
    example: str = ""
    origins: List[str] = field(default_factory=list)
    name: str = ""                # unique class name, assigned by build_maps

    @property
    def class_name(self) -> str:
        return self.name or self.role


def _role_for(prompt: str) -> str:
    for pattern, role in _ROLE_PATTERNS:
        if pattern.search(prompt or ""):
            return role
    return "Decider"


def _template_key(prompt: str, n: int = 5) -> str:
    """Leading significant words — calls sharing them get one JEV map sketch."""
    words = re.findall(r"[a-z']+", (prompt or "").lower())
    words = [w for w in words if w not in _STOPWORDS]
    return " ".join(words[:n])


def build_maps(items: List[MapItem]) -> List[JevMap]:
    buckets: Dict[Tuple[str, str], List[MapItem]] = {}
    for item in items:
        key = (_role_for(item.prompt), _template_key(item.prompt))
        buckets.setdefault(key, []).append(item)

    maps: List[JevMap] = []
    for (role, template), bucket in sorted(
        buckets.items(), key=lambda kv: -sum(i.weight for i in kv[1])
    ):
        outputs = [o for o in (" ".join(i.output.strip().lower().split()) for i in bucket) if o]
        distinct = sorted(set(outputs))

        kind, options, note = "Choice", None, None
        if outputs and all(o in _BOOL_WORDS for o in distinct):
            options = sorted(distinct, key=lambda x: (x != "yes", x != "true"))
        elif outputs and all(_NUMBER_RE.fullmatch(o) for o in distinct):
            nums = [float(o) for o in distinct]
            kind, options = "Score", (min(nums), max(nums))
        elif outputs and outputs[0][:1] in "{[":
            note = "output is JSON — map each field to a Choice option or Score range"
        elif len(distinct) <= 10:
            options = distinct
        else:
            note = f"{len(distinct)} distinct outputs — narrow the option set before migrating"

        maps.append(
            JevMap(
                role=role,
                template=template or "(mixed)",
                kind=kind,
                calls=sum(i.weight for i in bucket),
                score_range=(min(i.score for i in bucket), max(i.score for i in bucket)),
                options=options,
                note=note,
                example=min((i.prompt for i in bucket if i.prompt), key=len, default=""),
                origins=sorted({i.origin for i in bucket if i.origin})[:5],
            )
        )

    _assign_unique_names(maps)
    return maps


def _assign_unique_names(maps: List[JevMap]) -> None:
    """Role + leading template word(s), de-duplicated (RouterYou, RouterYou2, …)."""
    used: Dict[str, int] = {}
    for m in maps:
        words = [w for w in re.findall(r"[a-z]+", m.template.lower()) if w != "you"]
        candidates = [m.role] + [f"{m.role}{w.capitalize()}" for w in words[:3]]
        name = next((c for c in candidates if c not in used), None)
        if name is None:
            base = candidates[-1]
            n = used.get(base, 0) + 1
            name = base if n == 1 and base not in used else f"{base}{n}"
            used[base] = n
        else:
            used[name] = 1
        m.name = name
