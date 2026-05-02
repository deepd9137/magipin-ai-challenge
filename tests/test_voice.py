from __future__ import annotations

import pytest

from bot.composer.voice import VOICE_PACKS, get_voice


def test_voice_pack_dentists_tone():
    vp = get_voice("dentists")
    assert vp["tone"] == "peer_clinical"


def test_voice_pack_dentists_salutation():
    vp = get_voice("dentists")
    assert "Dr." in vp["salutation"]


def test_voice_pack_dentists_has_taboo():
    vp = get_voice("dentists")
    taboo = vp["vocab_taboo"]
    assert isinstance(taboo, list)
    assert len(taboo) > 0
    assert any("guaranteed" in w for w in taboo)


def test_voice_pack_dentists_has_voice_instructions():
    vp = get_voice("dentists")
    assert "clinical" in vp["voice_instructions"].lower()


def test_voice_pack_salons():
    vp = get_voice("salons")
    assert vp["tone"] == "warm_practical"
    assert "amazing" in vp["vocab_taboo"]


def test_voice_pack_restaurants():
    vp = get_voice("restaurants")
    assert vp["tone"] == "operator_to_operator"
    assert any("delicious" in w for w in vp["vocab_taboo"])


def test_voice_pack_gyms():
    vp = get_voice("gyms")
    assert vp["tone"] == "coach_motivational"
    assert "members" in vp["voice_instructions"]


def test_voice_pack_pharmacies():
    vp = get_voice("pharmacies")
    assert vp["tone"] == "trustworthy_precise"
    assert any("miracle" in w for w in vp["vocab_taboo"])


def test_voice_pack_unknown_falls_back_to_restaurants():
    vp = get_voice("unknown_category_xyz")
    assert vp["tone"] == VOICE_PACKS["restaurants"]["tone"]


def test_voice_pack_empty_slug_falls_back():
    vp = get_voice("")
    assert vp is not None
    assert "tone" in vp


def test_all_five_categories_present():
    for slug in ("dentists", "salons", "restaurants", "gyms", "pharmacies"):
        vp = get_voice(slug)
        assert vp["tone"] != ""
        assert "voice_instructions" in vp
