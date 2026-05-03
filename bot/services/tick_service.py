from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..composer.composer import compose
from ..composer.customer_composer import compose_customer_facing
from ..consent import TRIGGER_KIND_TO_CONSENT_SCOPE, has_consent
from ..llm.adapter import LLMProvider
from ..state import StateStore, Turn
from ..suppression import SuppressionTracker

log = logging.getLogger(__name__)

MAX_ACTIONS = 20
TICK_DEADLINE = 28.0   # seconds — overall budget for the entire /v1/tick call
COMPOSE_TIMEOUT = 22.0  # seconds — per-trigger LLM budget (fits 2 retries within TICK_DEADLINE)


def _parse_dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _now_utc(now_str: str) -> datetime:
    dt = _parse_dt(now_str)
    return dt if dt is not None else datetime.now(timezone.utc)


class TickService:
    def __init__(self, store: StateStore, llm: LLMProvider) -> None:
        self.store = store
        self.llm = llm
        self.suppression = SuppressionTracker(store)

    async def handle(self, now_str: str, available_triggers: List[str]) -> Dict[str, Any]:
        now = _now_utc(now_str)

        # ── Phase 1: fast filter (no LLM) ────────────────────────────────────
        # Tuple: (trg_id, category, merchant, trigger_data, customer, conv_id, cid, mid, scope)
        candidates: List[Tuple] = []

        for trg_id in available_triggers[:MAX_ACTIONS * 2]:
            if len(candidates) >= MAX_ACTIONS:
                break

            stored_trg = self.store.contexts.get(("trigger", trg_id))
            if not stored_trg:
                log.info("tick_skip reason=trigger_not_found id=%s", trg_id)
                continue

            t = stored_trg.payload

            # Expiry guard — skip without LLM call
            expires_at = _parse_dt(t.get("expires_at"))
            if expires_at and expires_at < now:
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"expired",'
                    '"details":"expires_at=%s"}',
                    trg_id, t.get("expires_at"),
                )
                continue

            # Suppression dedup
            suppression_key = t.get("suppression_key", "")
            if self.suppression.is_suppressed(suppression_key):
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"suppressed",'
                    '"details":"key=%s"}',
                    trg_id, suppression_key,
                )
                continue

            # Merchant resolution
            mid = t.get("merchant_id")
            if not mid:
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"no_merchant_id"}',
                    trg_id,
                )
                continue

            stored_merchant = self.store.contexts.get(("merchant", mid))
            if not stored_merchant:
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"merchant_missing",'
                    '"details":"merchant_id=%s"}',
                    trg_id, mid,
                )
                continue

            merchant = stored_merchant.payload
            cat_slug = merchant.get("category_slug")
            if not cat_slug:
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"no_category_slug",'
                    '"details":"merchant_id=%s"}',
                    trg_id, mid,
                )
                continue

            stored_cat = self.store.contexts.get(("category", cat_slug))
            if not stored_cat:
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"category_missing",'
                    '"details":"slug=%s"}',
                    trg_id, cat_slug,
                )
                continue

            category = stored_cat.payload

            # Customer resolution and consent gate (customer-scoped triggers only)
            scope = t.get("scope", "merchant")
            cid = t.get("customer_id")
            customer: Optional[Dict[str, Any]] = None

            if scope == "customer":
                if not cid:
                    log.info(
                        '{"event":"tick_skip_reason","trigger_id":"%s","reason":"customer_missing",'
                        '"details":"scope=customer but no customer_id"}',
                        trg_id,
                    )
                    continue

                stored_cust = self.store.contexts.get(("customer", cid))
                if not stored_cust:
                    log.info(
                        '{"event":"tick_skip_reason","trigger_id":"%s","reason":"customer_not_found",'
                        '"details":"customer_id=%s"}',
                        trg_id, cid,
                    )
                    continue

                customer = stored_cust.payload
                trigger_kind = t.get("kind", "")

                if not has_consent(customer, trigger_kind):
                    required_scope = TRIGGER_KIND_TO_CONSENT_SCOPE.get(trigger_kind, "any_consent")
                    log.info(
                        '{"event":"tick_skip_reason","trigger_id":"%s","reason":"consent_missing",'
                        '"details":"trigger_kind=%s requires %s consent","customer_id":"%s"}',
                        trg_id, trigger_kind, required_scope, cid,
                    )
                    continue

            trigger_data = {**t, "id": trg_id}
            conv_id = f"conv_{mid}_{trg_id}"

            candidates.append((trg_id, category, merchant, trigger_data, customer, conv_id, cid, mid, scope))

        if not candidates:
            return {"actions": []}

        # ── Phase 2: compose all candidates in parallel ───────────────────────
        loop = asyncio.get_event_loop()

        async def _compose_one(
            trg_id: str,
            category: dict,
            merchant: dict,
            trigger_data: dict,
            customer: Optional[dict],
            conv_id: str,
            cid: Optional[str],
            mid: str,
            scope: str,
            prior_bot_bodies: List[str],
        ) -> Optional[Tuple]:
            try:
                if scope == "customer" and customer is not None:
                    composer_fn = lambda: compose_customer_facing(
                        category, merchant, trigger_data, customer,
                        self.llm, prior_bot_bodies,
                    )
                else:
                    composer_fn = lambda: compose(
                        category, merchant, trigger_data,
                        customer, self.llm, prior_bot_bodies,
                    )

                result = await asyncio.wait_for(
                    loop.run_in_executor(None, composer_fn),
                    timeout=COMPOSE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                log.warning(
                    '{"event":"tick_timeout","trigger_id":"%s","merchant_id":"%s"}',
                    trg_id, mid,
                )
                return None
            except Exception as exc:
                log.warning(
                    '{"event":"tick_compose_error","trigger_id":"%s","merchant_id":"%s","error":"%s"}',
                    trg_id, mid, exc,
                )
                return None

            if result is None:
                return None
            return (trg_id, result, conv_id, cid, mid)

        tasks = [
            _compose_one(
                trg_id, cat, merch, tdata, cust, conv_id, cid, mid, scope,
                [turn.body for turn in self.store.conversations.get(conv_id, [])
                 if turn.from_role == "vera"],
            )
            for trg_id, cat, merch, tdata, cust, conv_id, cid, mid, scope in candidates
        ]

        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=TICK_DEADLINE)
        except asyncio.TimeoutError:
            log.warning("tick_deadline_exceeded returning partial actions")
            results = [t.result() if t.done() and not t.cancelled() else None for t in tasks]

        # ── Phase 3: collect actions ──────────────────────────────────────────
        # Dedup by suppression key within this tick — two triggers with the same key
        # both pass the pre-filter (checked before any composition) so we must enforce
        # uniqueness here as well.
        actions = []
        fired_this_tick: set[str] = set()

        for item in results:
            if item is None:
                continue
            trg_id, result, conv_id, cid, mid = item

            sk = result.suppression_key
            if sk and (self.suppression.is_suppressed(sk) or sk in fired_this_tick):
                log.info(
                    '{"event":"tick_skip_reason","trigger_id":"%s","reason":"suppressed_in_tick",'
                    '"details":"key=%s"}',
                    trg_id, sk,
                )
                continue

            if sk:
                fired_this_tick.add(sk)
            self.suppression.mark_fired(result.suppression_key)

            turns = self.store.conversations.setdefault(conv_id, [])
            turns.append(Turn(
                ts=datetime.now(timezone.utc),
                from_role="vera",
                body=result.body,
                kind="send",
                cta=result.cta,
            ))

            actions.append({
                "conversation_id": conv_id,
                "merchant_id": mid,
                "customer_id": cid,
                "send_as": result.send_as,
                "trigger_id": trg_id,
                "template_name": result.template_name,
                "template_params": result.template_params,
                "body": result.body,
                "cta": result.cta,
                "suppression_key": result.suppression_key,
                "rationale": result.rationale,
            })

        return {"actions": actions}
