"""M1 extraction unit tests: evidence routing, severity, language, contract. Free and
fast (no pipeline run, Claude disabled by conftest)."""
from __future__ import annotations

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
    ("Drain overflowing and a deep pothole near the station", None, "Waterlogging", "en", APP),  # 2 categories
    ("Please send someone, very bad condition near station.", None, "Pothole", "en", APP),          # 0 categories
    ("Something on the road", "A strange new photo text", "Pothole", "en", APP),                     # unknown photo
])
def test_unclear_cases_go_to_claude(desc, photo, reported, lang, ch):
    assert X.route(desc, photo, reported, lang, ch) == (None, "claude")


def test_claude_fallback_without_key_is_visible():
    r = X.classify("Drain overflowing and a deep pothole near the station", None, "Pothole", "en", APP)
    assert r["source"] == "claude_fallback" and r["category"] == "Pothole"
    r = X.classify("Something on the road", "A strange new photo text", "Other", "hi-en", APP)
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
    assert set(out.category_clean) <= set(X.CATEGORIES) | {X.NOT_ROAD}
    assert set(out.extraction_source) <= {"photo", "text", "citizen", "claude", "claude_fallback", "noise_fallback"}
    road = out.category_clean != X.NOT_ROAD
    assert out.severity_1_5[road].between(1, 5).all() and out.severity_1_5[~road].isna().all()



# ---- review fixes ------------------------------------------------------------------------

JUNK = ["Noise from construction at night", "Street light not working near building",
        "Garbage not collected for 3 days", "Hawkers blocking footpath", "Test",
        "Tree branch fallen on parked car", "Mosquito breeding in society compound", "asdfgh"]


@pytest.mark.parametrize("text", JUNK)
def test_non_road_complaints_are_rejected_not_turned_into_potholes(text):
    for reported in ("Pothole", "Road related", "Other"):
        r = X.classify(text, None, reported, "en", APP)
        assert r["category"] == X.NOT_ROAD and r["severity"] is None and r["source"] == "noise_fallback"


def test_every_junk_complaint_in_the_data_is_caught_and_nothing_else():
    c = read_csv("complaints")
    out = X.extract(c)
    noise = out[out.category_clean == X.NOT_ROAD]
    assert len(noise) == 120 and set(noise.description) == set(JUNK)
    linked = set(read_csv("work_orders").linked_complaint_ids.dropna().str.split("|").explode())
    assert not noise.complaint_id.isin(linked).any(), "a repaired road complaint was rejected as non-road"


def test_keyword_fixes_from_review():
    assert X.keyword_hits("Pot-hole reopened after last week's patch work") == ["Pothole"]
    assert X.keyword_hits("knee deep pothole near the market") == ["Pothole"]          # not waterlogging
    assert X.keyword_hits("Road has caved in. Big hole about knee deep.") == ["Road cave-in"]


def test_fallback_ignores_keywords_in_unreliable_text():
    # unknown photo + vague category + Hinglish text that names a category (near-random here)
    assert X._fallback("gutter ka dhakkan khula hai", "a new photo text", "Other", "hi-en", APP) == \
        (X.DEFAULT_CATEGORY, "claude_fallback")
    assert X._fallback("Drain overflowing and a pothole", None, "Other", "en", APP) == \
        ("Choked drain / nullah overflow", "claude_fallback")      # reliable text: first keyword


@pytest.mark.parametrize("text", ["कृपया लवकर दुरुस्त करा", "gutter ka dhakkan khula hai",
                                  "मैनहोल खुला है, बहुत खतरनाक है"])
def test_no_evidence_rows_take_the_most_common_category_without_claude(text, monkeypatch):
    """Unreliable text + vague category + no photo: Claude measured 19% vs 28.6% for the
    most common category on such linked complaints, so no Claude call is made."""
    calls = []
    monkeypatch.setattr(X.llm, "ask", lambda *a, **k: calls.append(a) or None)
    for lang in ("hi", "hi-en", "mr"):
        r = X.classify(text, None, "Other", lang, APP, "Dadar")
        assert (r["category"], r["source"]) == (X.DEFAULT_CATEGORY, "no_evidence")
        assert "field check" in r["english_summary"]
    assert calls == []


def test_summaries_are_honest_about_their_source():
    helpline = X.classify("Caller reports pothole at Jogeshwari East. Says vehicles getting damaged.",
                          None, "Pothole", "hi", HELP, "Jogeshwari East")
    assert helpline["english_summary"].startswith("Caller reports pothole")     # operator note kept verbatim
    noisy = X.classify("Hindmata mein school ke saamne paani bhar gaya hai", None, "Open or broken manhole",
                       "hi-en", APP, "Hindmata")
    assert "not translated" in noisy["english_summary"] and "citizen's selected category" in noisy["english_summary"]


def test_force_claude_bypasses_the_rules():
    text = ("Loose paver blocks on Ghatkopar Mankhurd Link Road, Trombay.", None, "Pothole", "en", APP)
    photo = ("x", "Wide shot of road with several potholes, auto rickshaw swerving", "Pothole", "hi", APP)
    for args in (text, photo):
        assert X.classify(*args)["source"] in ("text", "photo")
        assert X.classify(*args, force_claude=True)["source"] == "claude_fallback"   # Claude off in tests
    rec = {"description": text[0], "photo_description": None, "category_reported": "Pothole",
           "language": "en", "channel": APP, "locality_text": "Trombay", "ward_code": "M/E"}
    assert X.extract_complaint(rec, force_claude=True)["extraction_source"] == "claude_fallback"
    from evals import targets
    out = targets.resolve("extraction", "claude")({"input": rec})
    assert out["extraction_source"] in ("claude", "claude_fallback")


def test_extract_matches_classify_row_by_row():
    c = read_csv("complaints").sample(400, random_state=3)
    out = X.extract(c)
    for (_, r), (_, o) in zip(c.iterrows(), out.iterrows()):
        want = X.classify(r.description, r.photo_description, r.category_reported, r.language,
                          r.channel, r.locality_text)
        assert (o.category_clean, o.extraction_source) == (want["category"], want["source"]), r.complaint_id


def test_extract_complaint_is_thread_safe_on_first_use():
    from concurrent.futures import ThreadPoolExecutor
    X._RES.clear()
    blank = {"description": "Huge pothole near Dadar station", "photo_description": None,
             "category_reported": "Pothole", "language": "en", "channel": APP,
             "locality_text": "Dadar", "ward_code": None, "lat": None, "lon": None}
    given = {**blank, "ward_code": "G/N"}
    with ThreadPoolExecutor(8) as pool:
        outs = list(pool.map(X.extract_complaint, [blank, given] * 40))
    assert all(o["ward_code"] for o in outs)
