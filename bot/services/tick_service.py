from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..composer.composer import compose
from ..llm.adapter import LLMProvider
from ..state import StateStore

log = logging.getLogger(__name__)

MAX_ACTIONS = 20


def _parse_dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        # Handle Z suffix and +HH:MM offsets
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

    async def handle(self, now_str: str, available_triggers: List[str]) -> Dict[str, Any]:
        now = _now_utc(now_str)
        actions = []

        for trg_id in available_triggers[:MAX_ACTIONS * 2]:  # oversample; cap output
            if len(actions) >= MAX_ACTIONS:
                break

            stored_trg = self.store.contexts.get(("trigger", trg_id))
            if not stored_trg:
                log.info("tick_skip reason=trigger_not_found id=%s", trg_id)
                continue

            t = stored_trg.payload

            # Expiry check
            expires_at = _parse_dt(stored_trg.payload.get("expires_at") or t.get("expires_at"))
            if expires_at is None:
                # Check top-level expires_at on the stored payload
                expires_at = _parse_dt(stored_trg.payload.get("expires_at"))
            if expires_at and expires_at < now:
                log.info("tick_skip reason=expired id=%s expires=%s", trg_id, expires_at)
                continue

            # Suppression check
            suppression_key = t.get("suppression_key", "")
            if suppression_key and suppression_key in self.store.suppressed_keys:
                log.info("tick_skip reason=suppressed key=%s", suppression_key)
                continue

            # Merchant lookup
            mid = t.get("merchant_id")
            if not mid:
                log.info("tick_skip reason=no_merchant_id trigger=%s", trg_id)
                continue

            stored_merchant = self.store.contexts.get(("merchant", mid))
            if not stored_merchant:
                log.info("tick_skip reason=merchant_not_found merchant=%s", mid)
                continue

            merchant = stored_merchant.payload

            # Category lookup via merchant.category_slug
            cat_slug = merchant.get("category_slug")
            if not cat_slug:
                log.info("tick_skip reason=no_category_slug merchant=%s", mid)
                continue

            stored_cat = self.store.contexts.get(("category", cat_slug))
            if not stored_cat:
                log.info("tick_skip reason=category_not_found slug=%s", cat_slug)
                continue

            category = stored_cat.payload

            # Customer lookup (customer-scope triggers)
            customer: Optional[Dict[str, Any]] = None
            cid = t.get("customer_id")
            if cid:
                stored_cust = self.store.contexts.get(("customer", cid))
                if stored_cust:
                    customer = stored_cust.payload
                    # Consent gate: check trigger kind is in customer.consent.scope
                    trigger_kind = t.get("kind", "")
                    consent_scope = stored_cust.payload.get("consent", {}).get("scope", [])
                    if consent_scope and trigger_kind not in consent_scope:
                        log.info(
                            "tick_skip reason=consent_missing trigger_kind=%s customer=%s",
                            trigger_kind, cid,
                        )
                        continue
                else:
                    log.info("tick_skip reason=customer_not_found cid=%s", cid)
                    continue

            # Build the full trigger payload expected by composer
            trigger_data = {**t, "id": trg_id}

            # Run LLM composition in a thread (blocking SDK call → async wrapper)
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, compose, category, merchant, trigger_data, customer, self.llm
                    ),
                    timeout=27.0,  # 2s margin beyond LLM's internal 25s
                )
            except asyncio.TimeoutError:
                log.warning("tick_timeout trigger=%s", trg_id)
                continue
            except Exception as exc:
                log.warning("tick_compose_error trigger=%s error=%s", trg_id, exc)
                continue

            if result is None:
                continue

            # Mark suppression key as fired
            if result.suppression_key:
                self.store.suppressed_keys.add(result.suppression_key)

            conv_id = f"conv_{mid}_{trg_id}"

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
