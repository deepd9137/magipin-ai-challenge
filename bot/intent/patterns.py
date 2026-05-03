from __future__ import annotations

import re

AUTO_REPLY_PHRASES = [
    r"thank you for contacting",
    r"team will (?:respond|get back|reach out)",
    r"automated (?:assistant|reply|response)",
    r"this is an automated",
    r"please leave a (?:message|name)",
    r"hamari team (?:tak|aap se)",
    r"jaankari ke liye .* shukriya",
    r"out of office",
    r"will respond shortly",
]

OPT_OUT_PHRASES = [
    r"stop (?:messag|sending|spamm)",
    r"unsubscribe",
    r"don'?t (?:message|contact|call)",
    r"leave me alone",
    r"not interested.*(?:stop|don'?t)",
    r"band karo",
    r"mat bhejo",
]

HOSTILE_PHRASES = [
    r"\b(?:useless|bothering|harass|spam|annoying)\b",
    r"\b(?:stupid|idiotic|nonsense|bakwas|bekar)\b",
    r"why are you (?:bothering|messaging)",
]

# Strong commit phrases — INTENT_COMMIT regardless of prior history
COMMIT_PHRASES_STRONG = [
    r"^(?:yes|haan|ok|okay|sure|yep)\b.*(?:please|kar do|do it|go ahead|send|draft)",
    r"let'?s do (?:it|this)",
    r"(?:go|chal) (?:ahead|kar)",
    r"draft (?:it|kar|karo)",
    r"send (?:it|kar)",
    r"proceed",
]

# Bare affirmatives — only INTENT_COMMIT when prior Vera turn asked actionable question
COMMIT_PHRASES_BARE = [
    r"^(?:yes|haan|ok|okay|confirm)\.?$",
]

COMMIT_PHRASES = COMMIT_PHRASES_STRONG + COMMIT_PHRASES_BARE

OFF_TOPIC_KEYWORDS = [
    "gst", "tax filing", "loan", "credit card", "stock market",
    "weather", "cricket", "movie", "personal",
]

ACTIONABLE_PHRASES = [
    "want me to", "shall i", "should i",
    "draft", "send", "schedule",
    "kya draft", "bhej dun",
]


def matches_any(message: str, patterns: list[str]) -> bool:
    msg = message.lower()
    return any(re.search(p, msg, re.IGNORECASE) for p in patterns)
