"""M1 extraction unit tests: evidence routing, severity, language, contract. Free and
fast (no pipeline run, Claude disabled by conftest)."""
from __future__ import annotations

import pandas as pd
import pytest

from pipeline.connect import extract as X
from tests.conftest import read_csv

APP, HELP = "MyBMC App", "1916 Helpline"


def test_every_photo_template_in_the_data_maps_to_its_true_category():
    wo, c = read_csv("work_orders"), read_csv("complaints")
    links = (wo.dropna(subset=["linked_complaint_ids"])
             .assign(complaint_id=lambda d: d.linked_complaint_ids.str.split("|")).explode("complaint_id"))
    m = c.merge(links[["complaint_id", "work_type"]], on="complaint_id").dropna(subset=["photo_description"])
    got = m.photo_description.map(lambda p: X.photo_category(p)[0])
    assert got.notna().all(), "a photo template in the data is not in extract.PHOTO"
    assert (got == m.work_type).all()


def test_photo_beats_text_and_citizen():
    cat, src = X.route("मैनहोल खुला है", "Wide shot of road with several potholes, auto rickshaw swerving",
                       "Waterlogging", "hi", APP)
    assert (cat, src) == ("Pothole", "photo")


def test_english_text_overrides_a_wrong_citizen_category():
    cat, src = X.route("Loose paver blocks on Ghatkopar Mankhurd Link Road, Trombay.", None,
                       "Pothole", "en", APP)
    assert (cat, src) == ("Broken paver blocks", "text")


def test_helpline_notes_are_reliable_even_when_caller_language_is_not_english():
    cat, src = X.route("Citizen informs open or broken manhole at Anand Nagar, near masjid on LT Road.",
                       None, "Road related", "mr", HELP)
    assert (cat, src) == ("Open or broken manhole", "text")


def test_non_english_app_text_defers_to_the_citizen_category():
    # this text is statistically unrelated to the true category in the synthetic data
    cat, src = X.route("hospital gate के पास सड़क पर बड़ा गड्ढा है", None, "Waterlogging", "hi", APP)
    assert (cat, src) == ("Waterlogging", "citizen")


@pytest.mark.parametrize("desc,photo,reported,lang,ch", [
    ("Road has caved in near signal. Big hole about knee deep.", None, "Waterlogging", "en", APP),  # 2 categories
    ("Please send someone, very bad condition near station.", None, "Pothole", "en", APP),          # 0 categories
    ("कृपया लवकर दुरुस्त करा", None, "Other", "mr", APP),                                            # vague + unreliable
    ("Something on the road", "A strange new photo text", "Pothole", "en", APP),                     # unknown photo
])
def test_unclear_cases_go_to_claude(desc, photo, reported, lang, ch):
    assert X.route(desc, photo, reported, lang, ch) == (None, "claude")


def test_claude_fallback_without_key_is_visible():
    r = X.classify("Please send someone, very bad condition near station.", None, "Pothole", "en", APP)
    assert r["source"] == "claude_fallback" and r["category"] == "Pothole"
    r = X.classify("कृपया लवकर दुरुस्त करा", None, "Other", "mr", APP)
    assert r["source"] == "claude_fallback" and r["category"] == X.DEFAULT_CATEGORY


def test_caves_road_is_not_a_cave_in():
    assert X.keyword_hits("Caller reports pothole on Mahakali Caves Road.") == ["Pothole"]


def test_blocked_drain_is_not_paver_blocks():
    assert X.keyword_hits("Drain blocked with garbage near market") == ["Choked drain / nullah overflow"]


def test_severity_is_a_category_mode():
    """Mode of the true severity per category over linked complaints (what the eval
    scores). Drain is a 148/148 tie between 3 and 4; 3 also keeps 2s within one."""
    wo, c = read_csv("work_orders"), read_csv("complaints")
    links = (wo.dropna(subset=["linked_complaint_ids"])
             .assign(complaint_id=lambda d: d.linked_complaint_ids.str.split("|")).explode("complaint_id"))
    m = c.merge(links[["complaint_id", "work_type", "sla_hours"]], on="complaint_id")
    sev = m.sla_hours.map({24: 5, 48: 4, 72: 3, 120: 2, 168: 1})
    for cat, s in sev.groupby(m.work_type):
        assert X.severity_for(cat) in set(s.mode()), cat


@pytest.mark.parametrize("text,lang", [
    ("church जवळ रस्त्यावर मोठा खड्डा आहे, Andheri East. लवकर दुरुस्त करा.", "mr"),
    ("hospital gate के पास सड़क पर बड़ा गड्ढा है, Santacruz West. जल्दी ठीक करें.", "hi"),
    ("Hindmata mein school ke saamne paani bhar gaya hai ghutne tak", "hi-en"),
    ("Big pothole near the station, two wheelers falling daily.", "en"),
])
def test_language_detection_fallback(text, lang):
    assert X.detect_language(text) == lang


def test_given_language_wins_over_detection():
    # helpline notes are English even when the caller spoke Marathi
    r = X.classify("Citizen informs pothole at Tilak Nagar.", None, "Pothole", "mr", HELP)
    assert r["language"] == "mr"


def test_extract_complaint_contract():
    rec = {"complaint_id": "X", "channel": APP, "language": "en", "category_reported": "Other",
           "description": "Huge pothole near Dadar station, scooters falling.", "locality_text": "Dadar",
           "ward_code": None, "lat": None, "lon": None, "photo_description": None, "upvotes": 3}
    out = X.extract_complaint(rec)
    assert {"category_clean", "severity_1_5", "ward_code", "ward_source", "language",
            "english_summary", "extraction_source"} <= set(out)
    assert out["category_clean"] == "Pothole" and out["extraction_source"] == "text"
    assert out["ward_code"] is not None and out["ward_source"] == "locality"


def test_extract_dataframe_keeps_rows_and_tags_sources():
    c = read_csv("complaints").head(300)
    out = X.extract(c)
    assert len(out) == len(c) and out.index.equals(c.index)
    assert set(out.category_clean) <= set(X.CATEGORIES)
    assert set(out.extraction_source) <= {"photo", "text", "citizen", "claude", "claude_fallback"}
    assert out.severity_1_5.between(1, 5).all()
