from __future__ import annotations

from enum import Enum
from typing import Any, List, Union

from .patterns import (
    ACTIONABLE_PHRASES,
    AUTO_REPLY_PHRASES,
    COMMIT_PHRASES_BARE,
    COMMIT_PHRASES_STRONG,
    HOSTILE_PHRASES,
    OFF_TOPIC_KEYWORDS,
    OPT_OUT_PHRASES,
    matches_any,
)


class Intent(str, Enum):
    AUTO_REPLY = "auto_reply"
    OPT_OUT = "opt_out"
    HOSTILE = "hostile"
    INTENT_COMMIT = "intent_commit"
    OFF_TOPIC = "off_topic"
    ENGAGED = "engaged"
    UNCLEAR = "unclear"


def _get(turn: Any, key: str, default: str = "") -> str:
    """Access a Turn dataclass or plain dict uniformly."""
    if isinstance(turn, dict):
        return turn.get(key, default)
    return getattr(turn, key, default) or default


def classify(message: str, history: List[Any]) -> Intent:
    msg = message.strip()

    # 1. Hostile (check before opt-out — can co-occur)
    if matches_any(msg, HOSTILE_PHRASES):
        return Intent.HOSTILE

    # 2. Explicit opt-out
    if matches_any(msg, OPT_OUT_PHRASES):
        return Intent.OPT_OUT

    # 3. Auto-reply — phrase match
    if matches_any(msg, AUTO_REPLY_PHRASES):
        return Intent.AUTO_REPLY
    # Auto-reply — repetition signal: already seen this exact short message from merchant before
    merchant_msgs = [_get(t, "body") for t in history if _get(t, "from_role") == "merchant"]
    if merchant_msgs.count(msg) >= 1 and len(msg) < 200:
        return Intent.AUTO_REPLY

    # 4. Intent commit — strong phrases always commit; bare affirmatives need prior actionable
    if matches_any(msg, COMMIT_PHRASES_STRONG):
        return Intent.INTENT_COMMIT
    if matches_any(msg, COMMIT_PHRASES_BARE):
        if _last_bot_asked_actionable(history):
            return Intent.INTENT_COMMIT
        # bare affirmative without prior actionable question → fall through to engaged

    # 5. Off-topic — keyword + question mark
    if any(kw in msg.lower() for kw in OFF_TOPIC_KEYWORDS) and "?" in msg:
        return Intent.OFF_TOPIC

    # 6. Default
    if msg:
        return Intent.ENGAGED
    return Intent.UNCLEAR


def _last_bot_asked_actionable(history: List[Any]) -> bool:
    for turn in reversed(history):
        if _get(turn, "from_role") == "vera":
            body = _get(turn, "body").lower()
            return any(phrase in body for phrase in ACTIONABLE_PHRASES)
    return False
