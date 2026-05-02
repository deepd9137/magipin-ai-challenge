from __future__ import annotations

import pytest

from bot.composer.triggers import TRIGGER_FRAMINGS, get_framing


def test_framing_research_digest_has_citation_guidance():
    framing = get_framing("research_digest")
    assert "cite" in framing.lower() or "source" in framing.lower()


def test_framing_research_digest_has_merchant_anchor():
    framing = get_framing("research_digest")
    assert "merchant" in framing.lower()


def test_framing_regulation_change_mentions_deadline():
    framing = get_framing("regulation_change")
    assert "deadline" in framing.lower()


def test_framing_perf_dip_diagnose_and_reframe():
    framing = get_framing("perf_dip")
    assert "diagnose" in framing.lower() or "dip" in framing.lower()
    assert "concrete" in framing.lower() or "next step" in framing.lower()


def test_framing_perf_spike_acknowledge_win():
    framing = get_framing("perf_spike")
    assert "win" in framing.lower() or "acknowledge" in framing.lower()


def test_framing_recall_due_is_customer_facing():
    framing = get_framing("recall_due")
    assert "customer" in framing.upper() or "CUSTOMER" in framing


def test_framing_renewal_due_mentions_value():
    framing = get_framing("renewal_due")
    assert "value" in framing.lower() or "renew" in framing.lower()


def test_framing_festival_upcoming_category_specific():
    framing = get_framing("festival_upcoming")
    assert "salon" in framing.lower() or "restaurant" in framing.lower()


def test_framing_curious_ask_due_cialdini():
    framing = get_framing("curious_ask_due")
    assert "reciprocity" in framing.lower() or "cialdini" in framing.lower()


def test_framing_customer_lapsed_soft_no_shame():
    framing = get_framing("customer_lapsed_soft")
    assert "warm" in framing.lower() or "no-shame" in framing.lower()


def test_framing_customer_lapsed_hard_risk_reversal():
    framing = get_framing("customer_lapsed_hard")
    assert "risk" in framing.lower() or "trial" in framing.lower()


def test_framing_supply_alert_mentions_batches():
    framing = get_framing("supply_alert")
    assert "batch" in framing.lower() or "urgency" in framing.lower()


def test_framing_seasonal_perf_dip_normal_expected():
    framing = get_framing("seasonal_perf_dip")
    assert "normal" in framing.lower() or "seasonal" in framing.lower()


def test_framing_active_planning_intent_complete_artifact():
    framing = get_framing("active_planning_intent")
    assert "artifact" in framing.lower() or "drafted" in framing.lower()


def test_framing_unknown_trigger_returns_default():
    framing = get_framing("totally_unknown_trigger_kind_xyz")
    assert isinstance(framing, str)
    assert len(framing) > 10


def test_all_14_core_trigger_kinds_covered():
    core_kinds = [
        "research_digest", "regulation_change", "perf_dip", "perf_spike",
        "recall_due", "renewal_due", "festival_upcoming", "curious_ask_due",
        "customer_lapsed_soft", "customer_lapsed_hard", "competitor_opened",
        "review_theme_emerged", "milestone_reached", "seasonal_perf_dip",
    ]
    for kind in core_kinds:
        framing = get_framing(kind)
        assert framing != get_framing("totally_unknown_trigger_kind_xyz"), (
            f"{kind} should have a dedicated framing, not the default"
        )
