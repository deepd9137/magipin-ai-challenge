from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..llm.adapter import LLMProvider
from ..state import ComposedMessage
from ..validation.validators import validate
from .prompts import build_system_prompt, build_user_prompt
from .triggers import get_framing
from .voice import get_voice

log = logging.getLogger(__name__)

VALID_CTA = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
_URL_RE = re.compile(r"https?://|www\.|\.com/|bit\.ly", re.IGNORECASE)


def _parse_json(raw: str) -> Optional[dict]:
    """Extract JSON from LLM output, tolerating markdown code fences."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def _validate(body: str, cta: str, taboo: list) -> list[str]:
    """Simple 4-check validation (kept for backward compatibility with tests).
    For full 6-check validation use bot.validation.validators.validate()."""
    failures = []
    if not body:
        return ["empty_body"]
    if len(body) < 10:
        failures.append("body_too_short")
    if len(body) > 800:
        failures.append("body_too_long")
    if _URL_RE.search(body):
        failures.append("url_in_body")
    if cta not in VALID_CTA:
        failures.append(f"invalid_cta:{cta}")
    for word in taboo:
        if word.lower() in body.lower():
            failures.append(f"taboo_word:{word}")
    return failures


def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
    llm: LLMProvider,
    prior_bot_bodies: Optional[List[str]] = None,
) -> Optional[ComposedMessage]:
    """
    7-step composition pipeline:
    1. Context distillation (build_user_prompt)
    2. Voice pack lookup (get_voice by category slug)
    3. Trigger framing (get_framing by trigger kind)
    4. Build system + user prompts
    5. LLM call (temp=0, max_tokens=800, timeout=25s)
    6. Parse JSON response
    7. Full 6-check validation — one retry on failure with explicit feedback
    """
    prior_bot_bodies = prior_bot_bodies or []
    merchant_id = trigger.get("merchant_id", "unknown")
    trigger_kind = trigger.get("kind", "unknown")
    trigger_id = trigger.get("id", "unknown")

    cat_slug = category.get("slug", "")
    voice_pack = get_voice(cat_slug)
    framing = get_framing(trigger_kind)
    system = build_system_prompt(voice_pack, framing)
    user_prompt = build_user_prompt(category, merchant, trigger, customer)

    prev_failures: Optional[List[str]] = None

    for attempt in range(2):
        current_user = user_prompt
        if attempt == 1 and prev_failures:
            current_user += (
                f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION: {prev_failures}. "
                "Fix ALL of these issues in your next response. "
                "No URLs. No taboo words. CTA must be one of: "
                "open_ended, binary_yes_no, binary_confirm_cancel, multi_choice_slot, none. "
                "Every number/percentage in the body MUST appear verbatim in the provided context."
            )

        t0 = time.time()
        try:
            raw = llm.complete(system, current_user, max_tokens=400, temperature=0.0, timeout=22)
        except Exception as exc:
            log.warning(
                "llm_error attempt=%d trigger=%s merchant=%s error=%s",
                attempt, trigger_id, merchant_id, exc,
            )
            return None

        latency_ms = int((time.time() - t0) * 1000)
        parsed = _parse_json(raw)

        if parsed is None:
            log.warning(
                "llm_parse_fail attempt=%d trigger=%s raw_preview=%s",
                attempt, trigger_id, raw[:200],
            )
            if attempt == 0:
                user_prompt += "\n\nPrevious response was not valid JSON. Output ONLY the JSON object."
            continue

        body = parsed.get("body", "").strip()
        cta = parsed.get("cta", "open_ended")
        rationale = parsed.get("rationale", "")

        if body == "":
            log.info("compose_skip trigger=%s rationale=%s", trigger_id, rationale)
            return None

        val_result = validate(body, cta, category, merchant, trigger, customer, prior_bot_bodies)

        if val_result.valid:
            scope = trigger.get("scope", "merchant")
            send_as = "merchant_on_behalf" if scope == "customer" else "vera"
            owner = merchant.get("identity", {}).get("owner_first_name", "")
            template_name = f"vera_{trigger_kind}_v1"

            log.info(
                '{"event":"compose_action","trigger_id":"%s","merchant_id":"%s",'
                '"trigger_kind":"%s","llm_latency_ms":%d,"attempt":%d,'
                '"suppression_key":"%s","body_chars":%d}',
                trigger_id, merchant_id, trigger_kind, latency_ms, attempt,
                trigger.get("suppression_key", ""), len(body),
            )

            return ComposedMessage(
                body=body,
                cta=cta if cta in VALID_CTA else "open_ended",
                send_as=send_as,
                suppression_key=trigger.get("suppression_key", ""),
                rationale=rationale,
                template_name=template_name,
                template_params=[owner] if owner else [],
            )

        prev_failures = val_result.failures
        log.warning(
            "validation_fail attempt=%d trigger=%s failures=%s",
            attempt, trigger_id, val_result.failures,
        )

    return None
