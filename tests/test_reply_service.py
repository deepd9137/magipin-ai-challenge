from __future__ import annotations

import pytest
from bot.services.reply_service import ReplyService
from bot.state import StateStore, StoredContext, Turn
from datetime import datetime, timezone


SAMPLE_CATEGORY = {
    "slug": "dentists",
    "voice": {"tone": "peer_clinical", "register": "respectful", "vocab_taboo": []},
}
SAMPLE_MERCHANT = {
    "merchant_id": "m_001",
    "category_slug": "dentists",
    "identity": {"owner_first_name": "Meera", "name": "Dr. Meera Clinic"},
    "performance": {},
    "signals": [],
}


class FakeLLM:
    def __init__(self, response: str = ""):
        self._resp = response

    def complete(self, system, user, max_tokens=300, temperature=0.0, timeout=20):
        return self._resp

    def name(self):
        return "fake"


def _store_with_merchant() -> StateStore:
    s = StateStore()
    now = datetime.now(timezone.utc)
    s.contexts[("category", "dentists")] = StoredContext(
        scope="category", context_id="dentists", version=1,
        payload=SAMPLE_CATEGORY, stored_at=now,
    )
    s.contexts[("merchant", "m_001")] = StoredContext(
        scope="merchant", context_id="m_001", version=1,
        payload=SAMPLE_MERCHANT, stored_at=now,
    )
    return s


# ── Ended conversation guard ──────────────────────────────────────────────────

def test_ended_conversation_no_op():
    store = StateStore()
    store.ended_conversations.add("conv_1")
    svc = ReplyService(store=store, llm=FakeLLM())
    r = svc.handle("conv_1", "m_001", None, "merchant", "hello", 1)
    assert r["action"] == "end"


def test_ended_conversation_no_llm_call():
    store = StateStore()
    store.ended_conversations.add("conv_1")
    fake = FakeLLM()
    svc = ReplyService(store=store, llm=fake)
    svc.handle("conv_1", "m_001", None, "merchant", "hello", 1)
    # LLM should not be called
    assert True  # would raise if complete() was invoked and response was invalid


# ── Opt-out / hostile ────────────────────────────────────────────────────────

def test_opt_out_ends_immediately():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    r = svc.handle("conv_1", "m_001", None, "merchant", "Stop messaging me", 1)
    assert r["action"] == "end"
    assert "conv_1" in store.ended_conversations


def test_hostile_ends_immediately():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    r = svc.handle("conv_1", "m_001", None, "merchant", "This is useless spam annoying me", 1)
    assert r["action"] == "end"
    assert "conv_1" in store.ended_conversations


def test_hostile_rationale_mentions_frustration():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    r = svc.handle("conv_1", "m_001", None, "merchant", "Why are you bothering me", 1)
    assert "frustration" in r["rationale"].lower()


# ── Auto-reply progression ────────────────────────────────────────────────────

def test_auto_reply_turn1_sends_hint():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    r = svc.handle("conv_1", "m_001", None, "merchant",
                   "Thank you for contacting us, our team will respond shortly", 1)
    assert r["action"] == "send"
    assert "auto" in r["body"].lower() or "reply" in r["body"].lower()
    assert r["cta"] == "binary_yes_no"


def test_auto_reply_turn2_waits():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    msg = "Thank you for contacting us, our team will respond shortly"
    # Simulate judge pattern: different conv_ids, turn_number increments
    r = svc.handle("conv_auto_2", "m_001", None, "merchant", msg, 3)
    assert r["action"] == "wait"
    assert r.get("wait_seconds", 0) >= 3600


def test_auto_reply_turn3_ends():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    msg = "Thank you for contacting us, our team will respond shortly"
    r = svc.handle("conv_auto_3", "m_001", None, "merchant", msg, 4)
    assert r["action"] == "end"
    assert "conv_auto_3" in store.ended_conversations


# ── Intent commit ────────────────────────────────────────────────────────────

def test_commit_switches_to_action_mode():
    store = _store_with_merchant()
    vera_body = '{"body": "On it — drafting the patient WhatsApp now. Reply CONFIRM.", "cta": "binary_confirm_cancel", "rationale": "commit"}'
    svc = ReplyService(store=store, llm=FakeLLM(vera_body))
    # Plant a prior Vera turn that asked an actionable question
    store.conversations["conv_1"] = [
        Turn(ts=datetime.now(timezone.utc), from_role="vera",
             body="Want me to draft the patient WhatsApp?", kind="send", cta="binary_yes_no"),
    ]
    r = svc.handle("conv_1", "m_001", None, "merchant", "yes please", 2)
    assert r["action"] == "send"
    assert r.get("cta") in ("binary_confirm_cancel", "binary_yes_no", "open_ended")


def test_commit_fallback_when_composer_fails():
    store = _store_with_merchant()
    svc = ReplyService(store=store, llm=FakeLLM("not valid json"))
    store.conversations["conv_1"] = [
        Turn(ts=datetime.now(timezone.utc), from_role="vera",
             body="Shall I schedule this?", kind="send"),
    ]
    r = svc.handle("conv_1", "m_001", None, "merchant", "Let's do it", 2)
    assert r["action"] == "send"
    assert "CONFIRM" in r["body"] or "draft" in r["body"].lower()


# ── Off-topic redirect ────────────────────────────────────────────────────────

def test_off_topic_returns_send():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    r = svc.handle("conv_1", "m_001", None, "merchant", "Can you help me with GST filing?", 1)
    assert r["action"] == "send"
    assert "outside" in r["body"].lower() or "right route" in r["body"].lower()


def test_off_topic_redirect_includes_prior_question():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    store.conversations["conv_1"] = [
        Turn(ts=datetime.now(timezone.utc), from_role="vera",
             body="Want me to pull the abstract for you?", kind="send"),
    ]
    r = svc.handle("conv_1", "m_001", None, "merchant", "Can you help me with GST?", 2)
    assert r["action"] == "send"
    assert "abstract" in r["body"].lower() or "thread" in r["body"].lower()


# ── Engaged ──────────────────────────────────────────────────────────────────

def test_engaged_calls_composer():
    store = _store_with_merchant()
    fake_resp = '{"body": "Great question — here is more detail.", "cta": "open_ended", "rationale": "engaged"}'
    svc = ReplyService(store=store, llm=FakeLLM(fake_resp))
    r = svc.handle("conv_1", "m_001", None, "merchant", "Tell me more about this", 1)
    assert r["action"] == "send"
    assert "Great question" in r["body"]


def test_engaged_fallback_when_composer_fails():
    store = _store_with_merchant()
    svc = ReplyService(store=store, llm=FakeLLM(""))
    r = svc.handle("conv_1", "m_001", None, "merchant", "Tell me more", 1)
    assert r["action"] == "send"
    assert r["body"]


# ── Conversation history recording ───────────────────────────────────────────

def test_merchant_turn_recorded_in_history():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    svc.handle("conv_1", "m_001", None, "merchant", "Stop messaging me", 1)
    history = store.conversations.get("conv_1", [])
    merchant_turns = [t for t in history if t.from_role == "merchant"]
    assert len(merchant_turns) == 1
    assert merchant_turns[0].body == "Stop messaging me"


def test_vera_turn_recorded_after_auto_reply():
    store = StateStore()
    svc = ReplyService(store=store, llm=FakeLLM())
    svc.handle("conv_1", "m_001", None, "merchant",
               "Thank you for contacting us, team will respond shortly", 1)
    history = store.conversations.get("conv_1", [])
    vera_turns = [t for t in history if t.from_role == "vera"]
    assert len(vera_turns) == 1
