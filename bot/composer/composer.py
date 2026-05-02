from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional

from ..llm.adapter import LLMProvider
from ..state import ComposedMessage
from .prompts import BASE_SYSTEM, build_user_prompt

log = logging.getLogger(__name__)

VALID_CTA = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
_URL_RE = re.compile(r"https?://|www\.|\.com/|bit\.ly", re.IGNORECASE)


def _parse_json(raw: str) -> Optional[dict]:
    """Extract JSON from LLM output, tolerating markdown code fences."""
    text = raw.strip()
    # Strip optional ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last-resort: find the first {...} block
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def _validate(body: str, cta: str, taboo: list) -> list[str]:
    """Return list of validation failure reasons (empty = pass)."""
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
) -> Optional[ComposedMessage]:
    """
    7-step composition pipeline:
    1. Context distillation (handled in build_user_prompt)
    2. Voice pack lookup (tone/taboo from category.voice)
    3. Trigger framing (handled via full context in prompt)
    4. Build prompt
    5. LLM call (temp=0, max_tokens=800, timeout=25s)
    6. Parse JSON response
    7. Validation (length, no URLs, no taboo, CTA shape) — one retry on failure
    """
    taboo_vocab = category.get("voice", {}).get("vocab_taboo", [])
    merchant_id = trigger.get("merchant_id", "unknown")
    trigger_kind = trigger.get("kind", "unknown")
    trigger_id = trigger.get("id", "unknown")

    user_prompt = build_user_prompt(category, merchant, trigger, customer)

    for attempt in range(2):
        t0 = time.time()
        try:
            raw = llm.complete(BASE_SYSTEM, user_prompt, max_tokens=800, temperature=0.0, timeout=25)
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

        # Skip trigger if LLM intentionally returned empty body
        if body == "":
            log.info("compose_skip trigger=%s rationale=%s", trigger_id, rationale)
            return None

        failures = _validate(body, cta, taboo_vocab)

        if failures:
            log.warning(
                "validation_fail attempt=%d trigger=%s failures=%s",
                attempt, trigger_id, failures,
            )
            if attempt == 0:
                user_prompt += (
                    f"\n\nPrevious response failed validation: {failures}. "
                    "Fix these issues. No URLs. CTA must be one of: "
                    "open_ended, binary_yes_no, binary_confirm_cancel, multi_choice_slot, none."
                )
            continue

        scope = trigger.get("scope", "merchant")
        send_as = "merchant_on_behalf" if scope == "customer" else "vera"
        owner = merchant.get("identity", {}).get("owner_first_name", "")
        template_name = f"vera_{trigger_kind}_v1"

        log.info(
            '{"ts":"%s","event":"compose_action","trigger_id":"%s","merchant_id":"%s",'
            '"trigger_kind":"%s","llm_latency_ms":%d,"validation_passes":%s,'
            '"retry_count":%d,"suppression_key":"%s","body_chars":%d}',
            __import__("datetime").datetime.utcnow().isoformat() + "Z",
            trigger_id, merchant_id, trigger_kind, latency_ms,
            json.dumps([v for v in ["length", "no_url", "no_taboo", "cta_shape"] if v not in str(failures)]),
            attempt, trigger.get("suppression_key", ""), len(body),
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

    return None
