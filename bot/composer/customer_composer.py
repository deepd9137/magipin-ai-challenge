from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..language import resolve_language
from ..llm.adapter import LLMProvider
from ..state import ComposedMessage
from ..validation.validators import validate
from .prompts import build_customer_system_prompt, build_customer_user_prompt
from .triggers import get_framing
from .voice import get_customer_voice

log = logging.getLogger(__name__)

VALID_CTA = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
_URL_RE = re.compile(r"https?://|www\.|\.com/|bit\.ly", re.IGNORECASE)


def _parse_json(raw: str) -> Optional[dict]:
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


def compose_customer_facing(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Dict[str, Any],
    llm: LLMProvider,
    prior_bot_bodies: Optional[List[str]] = None,
) -> Optional[ComposedMessage]:
    """Customer-facing variant of the 7-step composition pipeline.

    Composes a message sent FROM the merchant TO a specific customer.
    Always returns send_as='merchant_on_behalf'.
    Customer language preference overrides merchant languages.
    """
    prior_bot_bodies = prior_bot_bodies or []
    merchant_id = trigger.get("merchant_id", "unknown")
    trigger_kind = trigger.get("kind", "unknown")
    trigger_id = trigger.get("id", "unknown")
    customer_id = customer.get("customer_id") or trigger.get("customer_id", "unknown")

    language = resolve_language(merchant, customer)
    voice_pack = get_customer_voice(category.get("slug", ""))
    framing = get_framing(trigger_kind)

    system = build_customer_system_prompt(voice_pack, framing, language)
    user_prompt = build_customer_user_prompt(category, merchant, trigger, customer)

    prev_failures: Optional[List[str]] = None

    for attempt in range(2):
        current_user = user_prompt
        if attempt == 1 and prev_failures:
            current_user += (
                f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION: {prev_failures}. "
                "Fix ALL of these issues. No URLs. No taboo words. "
                "CTA must be one of: binary_yes_no, multi_choice_slot, binary_confirm_cancel, none. "
                "Every number in the body MUST appear verbatim in the provided context."
            )

        t0 = time.time()
        try:
            raw = llm.complete(system, current_user, max_tokens=400, temperature=0.0, timeout=22)
        except Exception as exc:
            log.warning(
                "customer_llm_error attempt=%d trigger=%s customer=%s error=%s",
                attempt, trigger_id, customer_id, exc,
            )
            return None

        latency_ms = int((time.time() - t0) * 1000)
        parsed = _parse_json(raw)

        if parsed is None:
            log.warning(
                "customer_llm_parse_fail attempt=%d trigger=%s raw_preview=%s",
                attempt, trigger_id, raw[:200],
            )
            if attempt == 0:
                user_prompt += "\n\nPrevious response was not valid JSON. Output ONLY the JSON object."
            continue

        body = parsed.get("body", "").strip()
        cta = parsed.get("cta", "binary_yes_no")
        rationale = parsed.get("rationale", "")

        if body == "":
            log.info(
                "customer_compose_skip trigger=%s customer=%s rationale=%s",
                trigger_id, customer_id, rationale,
            )
            return None

        val_result = validate(body, cta, category, merchant, trigger, customer, prior_bot_bodies)

        if val_result.valid:
            template_name = f"vera_customer_{trigger_kind}_v1"
            cust_name = customer.get("identity", {}).get("name", "")

            log.info(
                '{"event":"customer_compose_action","trigger_id":"%s","merchant_id":"%s",'
                '"customer_id":"%s","trigger_kind":"%s","language":"%s",'
                '"llm_latency_ms":%d,"attempt":%d,"body_chars":%d}',
                trigger_id, merchant_id, customer_id, trigger_kind, language,
                latency_ms, attempt, len(body),
            )

            return ComposedMessage(
                body=body,
                cta=cta if cta in VALID_CTA else "binary_yes_no",
                send_as="merchant_on_behalf",
                suppression_key=trigger.get("suppression_key", ""),
                rationale=rationale,
                template_name=template_name,
                template_params=[cust_name] if cust_name else [],
            )

        prev_failures = val_result.failures
        log.warning(
            "customer_validation_fail attempt=%d trigger=%s customer=%s failures=%s",
            attempt, trigger_id, customer_id, val_result.failures,
        )

    return None
