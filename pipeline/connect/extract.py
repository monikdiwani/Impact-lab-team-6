"""Category / severity / English summary (owner: M1).

Claude structured extraction runs on non-English and vague ("Road related"/"Other")
complaints when a cache entry or API key exists; otherwise a keyword fallback is used.
Each row is tagged with its source so the share done by Claude is measurable.
"""
from __future__ import annotations

import re

import pandas as pd

from pipeline.common import llm

CATEGORIES = ["Pothole", "Waterlogging", "Open or broken manhole",
              "Choked drain / nullah overflow", "Road cave-in", "Broken paver blocks"]
VAGUE = {"Road related", "Other"}

SYSTEM = ("You triage Mumbai civic road complaints written in English, Hindi, Marathi or "
          "Hinglish. Return JSON only. Do not invent facts that are not in the text.")
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["category", "severity", "english_summary"],
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "severity": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "english_summary": {"type": "string"},
    },
}

_KW = [  # most specific first
    ("Road cave-in", r"cave|sink|sank|collaps|धंस|खचल|dhans|khachal"),
    ("Open or broken manhole", r"manhole|man hole|chamber|मैनहोल|मॅनहोल|ढक्कन|zakkan|dhakkan"),
    ("Broken paver blocks", r"paver|block|tile|पेवर|फरश"),
    ("Choked drain / nullah overflow", r"drain|nullah|nala|गटार|नाला|नाली|gutter|sewage|overflow"),
    ("Waterlogging", r"water ?log|flood|paani|pani|पानी|साचल|sachal|submerg|knee"),
    ("Pothole", r"pot ?hole|gadda|gaddha|khadda|खड्ड|गड्ढ|गड्डा|crater|hole"),
]
_SEV_UP = (r"accident|injur|fell|school|hospital|ambulance|child|kids|elder|emergency|"
           r"dangerous|deep|cave|manhole|अपघात|शाळा|स्कूल|अस्पताल")


def _severity(desc: str, upvotes: int) -> int:
    s = 3
    if re.search(_SEV_UP, (desc or "").lower()):
        s += 1
    if upvotes >= 30:
        s += 1
    return max(1, min(5, s))


def _classify(desc: str, language: str, reported: str, upvotes: int):
    """-> (category, severity, english_summary, source)."""
    desc = desc or ""
    cat = reported if reported in CATEGORIES else None
    if cat is None:
        cat = next((c for c, rx in _KW if re.search(rx, desc.lower())), "Pothole")
    if language != "en" or reported in VAGUE:
        prompt = f"Complaint ({language}): {desc}\nReported category: {reported}"
        got = llm.ask(prompt, system=SYSTEM, effort="low", schema=SCHEMA, fallback=None)
        if isinstance(got, dict) and got.get("category") in CATEGORIES:
            return got["category"], int(got["severity"]), got["english_summary"], "claude"
    return cat, _severity(desc, upvotes), desc.strip()[:140], "rules"


def extract(df: pd.DataFrame) -> pd.DataFrame:
    res = [_classify(r.description, r.language, r.category_reported, r.upvotes)
           for r in df.itertuples()]
    out = df.copy()
    out["category_clean"], out["severity_1_5"] = [x[0] for x in res], [x[1] for x in res]
    out["english_summary"], out["extraction_source"] = [x[2] for x in res], [x[3] for x in res]
    return out


_RES: dict = {}


def extract_complaint(record: dict) -> dict:
    """Eval/app contract: one raw complaint dict -> cleaned fields."""
    from pipeline.common import io
    from pipeline.common.geo import WardLocator
    from pipeline.connect.ward import Gazetteer
    if not _RES:
        _RES["loc"] = WardLocator(io.load_wards_geojson())
        _RES["gaz"] = Gazetteer(io.load_localities())
    cat, sev, summary, _ = _classify(record.get("description"), record.get("language", "en"),
                                     record.get("category_reported"), int(record.get("upvotes") or 0))
    ward = record.get("ward_code")
    if not isinstance(ward, str) or not ward:
        lat, lon = record.get("lat"), record.get("lon")
        ward = _RES["loc"].locate(lat, lon) if lat is not None and lon is not None else None
        if ward is None:
            hit = _RES["gaz"].match(record.get("locality_text"), record.get("description"))
            ward = hit[1] if hit else None
    return {"category_clean": cat, "severity_1_5": sev, "ward_code": ward,
            "language": record.get("language"), "english_summary": summary}
