from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..llm.adapter import LLMProvider
from ..composer.voice import get_voice

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://|www\.|\.com/|bit\.ly", re.IGNORECASE)
VALID_CTA = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}


def _get(turn: Any, key: str, default: str = "") -> str:
    if isinstance(turn, dict):
        return turn.get(key, default)
    return getattr(turn, key, default) or default


def _history_text(history: List[Any], last_n: int = 6) -> str:
    lines = []
    for turn in history[-last_n:]:
        role = _get(turn, "from_role", "?")
        body = _get(turn, "body", "")
        lines.append(f"[{role}] {body}")
    return "\n".join(lines)


def compose_reply(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    history: List[Any],
    latest_intent: Any,
    llm: LLMProvider,
    customer: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    cat_slug = (category or {}).get("slug", "")
    voice = get_voice(cat_slug)
    owner = (merchant or {}).get("identity", {}).get("owner_first_name", "there")
    intent_val = latest_intent.value if hasattr(latest_intent, "value") else str(latest_intent)

    system = (
        f"You are Vera, a WhatsApp business assistant for Indian merchants on magicpin.\n"
        f"Voice: {voice.get('tone', 'friendly')}. Register: {voice.get('register', 'professional')}.\n"
        f"Taboo words (never use): {', '.join(voice.get('vocab_taboo', []))}.\n"
        "Rules:\n"
        "- Reply in 1-3 sentences (50-250 chars total).\n"
        "- No URLs ever.\n"
        "- Single CTA only.\n"
        "- Never fabricate numbers not present in merchant context.\n"
        'Output ONLY valid JSON: {"body": "...", "cta": "...", "rationale": "..."}'
    )

    merchant_summary = json.dumps({
        "name": (merchant or {}).get("identity", {}).get("name", ""),
        "owner": owner,
        "category": cat_slug,
        "performance": (merchant or {}).get("performance", {}),
        "signals": (merchant or {}).get("signals", []),
    }, ensure_ascii=False)

    user = (
        f"=== CONVERSATION HISTORY ===\n{_history_text(history)}\n\n"
        f"=== MERCHANT CONTEXT ===\n{merchant_summary}\n\n"
        f"Detected intent: {intent_val}\n"
        "Compose the next Vera reply. JSON only."
    )

    if intent_val == "intent_commit":
        user += (
            "\nINSTRUCTION: Merchant committed. Give ONE concrete next action "
            "(draft/schedule/send) with measurable scope. "
            "CTA must be binary_confirm_cancel. No qualifying questions."
        )

    try:
        raw = llm.complete(system, user, max_tokens=300, temperature=0.0, timeout=20)
    except Exception as exc:
        log.warning("reply_composer_llm_error intent=%s error=%s", intent_val, exc)
        return None

    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
            except json.JSONDecodeError:
                pass

    if parsed is None:
        log.warning("reply_composer_parse_fail raw=%s", raw[:200])
        return None

    body = parsed.get("body", "").strip()
    cta = parsed.get("cta", "open_ended")
    rationale = parsed.get("rationale", "")

    if not body or len(body) < 5 or len(body) > 800:
        return None
    if _URL_RE.search(body):
        return None
    if cta not in VALID_CTA:
        cta = "open_ended"

    return {"body": body, "cta": cta, "rationale": rationale}
