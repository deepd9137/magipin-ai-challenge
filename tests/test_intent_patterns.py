from __future__ import annotations

import pytest
from bot.intent.classifier import Intent, classify
from bot.state import Turn
from datetime import datetime, timezone


def _turn(role: str, body: str, intent: str = "") -> Turn:
    return Turn(
        ts=datetime.now(timezone.utc),
        from_role=role,
        body=body,
        kind="reply",
        intent_classified=intent,
    )


# ── Auto-reply phrase detection ───────────────────────────────────────────────

def test_auto_reply_phrase_thank_you():
    assert classify("Thank you for contacting us", []) == Intent.AUTO_REPLY


def test_auto_reply_phrase_team_will_respond():
    assert classify("Our team will respond shortly", []) == Intent.AUTO_REPLY


def test_auto_reply_phrase_automated():
    assert classify("This is an automated response", []) == Intent.AUTO_REPLY


def test_auto_reply_phrase_hindi():
    assert classify("Hamari team aap se sampark karegi", []) == Intent.AUTO_REPLY


def test_auto_reply_out_of_office():
    assert classify("I am out of office till Monday", []) == Intent.AUTO_REPLY


# ── Auto-reply repetition detection ──────────────────────────────────────────

def test_repetition_signals_auto_reply():
    msg = "Thanks for reaching out, will get back soon"
    history = [_turn("merchant", msg, "engaged")]
    assert classify(msg, history) == Intent.AUTO_REPLY


def test_repetition_long_message_not_auto_reply():
    msg = "x" * 201
    history = [_turn("merchant", msg)]
    assert classify(msg, history) != Intent.AUTO_REPLY


# ── Opt-out detection ─────────────────────────────────────────────────────────

def test_opt_out_stop_messaging():
    assert classify("Please stop messaging me", []) == Intent.OPT_OUT


def test_opt_out_hindi():
    assert classify("Band karo ye messages", []) == Intent.OPT_OUT


def test_opt_out_dont_contact():
    assert classify("Don't contact me anymore", []) == Intent.OPT_OUT


# ── Hostile detection ─────────────────────────────────────────────────────────

def test_hostile_useless_spam():
    assert classify("Why are you bothering me. This is useless spam.", []) == Intent.HOSTILE


def test_hostile_bakwas():
    assert classify("Ye sab bakwas hai", []) == Intent.HOSTILE


def test_hostile_before_opt_out():
    # "stop messaging me you are annoying" — hostile takes priority
    assert classify("stop messaging me you are annoying", []) == Intent.HOSTILE


# ── Intent commit ─────────────────────────────────────────────────────────────

def test_commit_with_prior_actionable():
    history = [_turn("vera", "Want me to draft the patient WhatsApp?", "")]
    assert classify("yes please", history) == Intent.INTENT_COMMIT


def test_commit_lets_do_it():
    history = [_turn("vera", "Shall I schedule this for tomorrow?", "")]
    assert classify("Let's do it", history) == Intent.INTENT_COMMIT


def test_commit_bare_yes_no_prior_actionable():
    # bare "yes" with NO prior actionable question → ENGAGED, not commit
    history = [_turn("vera", "Here are your stats for this week.", "")]
    assert classify("yes", history) == Intent.ENGAGED


def test_commit_no_history():
    # no history at all → engaged
    assert classify("ok", []) == Intent.ENGAGED


def test_commit_explicit_phrase_no_history():
    # "Let's do it" is a strong commit phrase — even without history
    assert classify("Let's do it", []) == Intent.INTENT_COMMIT


# ── Off-topic detection ───────────────────────────────────────────────────────

def test_off_topic_gst():
    assert classify("Can you help me with GST filing?", []) == Intent.OFF_TOPIC


def test_off_topic_loan():
    assert classify("Can I get a loan from magicpin?", []) == Intent.OFF_TOPIC


def test_off_topic_no_question_mark_not_off_topic():
    # keyword without "?" → not off-topic
    result = classify("I need to sort my gst", [])
    assert result != Intent.OFF_TOPIC


# ── Engaged / unclear ────────────────────────────────────────────────────────

def test_engaged_fallback():
    assert classify("Tell me more about it", []) == Intent.ENGAGED


def test_engaged_question():
    assert classify("How does this work?", []) == Intent.ENGAGED


def test_unclear_empty():
    assert classify("", []) == Intent.UNCLEAR
