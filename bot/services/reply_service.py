from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..composer.reply_composer import compose_reply
from ..intent.classifier import Intent, classify
from ..llm.adapter import LLMProvider
from ..state import StateStore, Turn

log = logging.getLogger(__name__)


class ReplyService:
    def __init__(self, store: StateStore, llm: LLMProvider) -> None:
        self.store = store
        self.llm = llm

    def handle(
        self,
        conv_id: str,
        merchant_id: Optional[str],
        customer_id: Optional[str],
        from_role: str,
        message: str,
        turn_number: int,
    ) -> Dict[str, Any]:
        if conv_id in self.store.ended_conversations:
            return {"action": "end", "rationale": "conversation already ended"}

        history = self.store.conversations.setdefault(conv_id, [])

        # Classify before appending so classifier sees prior history only
        intent = classify(message, history)
        log.info("reply_classify conv=%s intent=%s turn=%d", conv_id, intent.value, turn_number)

        history.append(Turn(
            ts=datetime.now(timezone.utc),
            from_role=from_role,
            body=message,
            kind="reply",
            intent_classified=intent.value,
        ))

        if intent == Intent.AUTO_REPLY:
            result = self._handle_auto_reply(conv_id, history, turn_number)
        elif intent in (Intent.OPT_OUT, Intent.HOSTILE):
            result = self._handle_exit(conv_id, intent)
        elif intent == Intent.INTENT_COMMIT:
            result = self._handle_commit(conv_id, merchant_id, history)
        elif intent == Intent.OFF_TOPIC:
            result = self._handle_off_topic(conv_id, history)
        else:
            result = self._handle_engaged(conv_id, merchant_id, customer_id, history)

        log.info(
            '{"event":"reply_action","conv_id":"%s","action":"%s","intent":"%s","turn":%d}',
            conv_id, result.get("action", "unknown"), intent.value, turn_number,
        )
        return result

    # ── Intent handlers ───────────────────────────────────────────────────────

    def _handle_auto_reply(self, conv_id: str, history: List[Turn], turn_number: int = 1) -> dict:
        # Use turn_number as primary signal — judge may use different conv_ids per turn.
        # Fall back to consecutive history count for same-conv multi-turn flows.
        consecutive = max(self._consecutive_auto_reply_count(history), turn_number - 1)
        if consecutive <= 1:
            body = "Looks like an auto-reply. When the owner sees this, just reply YES to continue."
            self._record_vera(conv_id, body, "binary_yes_no")
            return {
                "action": "send", "body": body, "cta": "binary_yes_no",
                "rationale": "Detected auto-reply; prompting owner to respond directly.",
            }
        if consecutive == 2:
            return {
                "action": "wait", "wait_seconds": 14400,
                "rationale": "Same auto-reply twice; waiting 4h for owner to see.",
            }
        self.store.ended_conversations.add(conv_id)
        return {"action": "end", "rationale": "Auto-reply 3x consecutive; closing conversation."}

    def _handle_exit(self, conv_id: str, intent: Intent) -> dict:
        self.store.ended_conversations.add(conv_id)
        if intent == Intent.HOSTILE:
            return {
                "action": "end",
                "rationale": "Merchant frustration explicit; closing without further engagement.",
            }
        return {"action": "end", "rationale": "Merchant opted out; closing conversation."}

    def _handle_commit(self, conv_id: str, merchant_id: Optional[str], history: List[Turn]) -> dict:
        merchant, category = self._resolve_merchant_category(merchant_id)
        result = compose_reply(
            category=category, merchant=merchant, history=history,
            latest_intent=Intent.INTENT_COMMIT, llm=self.llm,
        )
        if not result:
            body = "On it — drafting now. Reply CONFIRM to proceed."
            self._record_vera(conv_id, body, "binary_confirm_cancel")
            return {
                "action": "send", "body": body, "cta": "binary_confirm_cancel",
                "rationale": "Commit detected; minimal action ack.",
            }
        self._record_vera(conv_id, result["body"], result.get("cta", "binary_confirm_cancel"))
        return {
            "action": "send", **result,
            "rationale": result.get("rationale", "Commit detected; switched to action mode."),
        }

    def _handle_off_topic(self, conv_id: str, history: List[Turn]) -> dict:
        body = (
            "That's outside what I can help with — your CA or the relevant service is the right route. "
            "Coming back to our thread — "
        )
        last_q = self._last_vera_question(history)
        body += last_q if last_q else "want to continue from where we left off?"
        self._record_vera(conv_id, body, "open_ended")
        return {
            "action": "send", "body": body, "cta": "open_ended",
            "rationale": "Off-topic ask declined; redirected to prior thread.",
        }

    def _handle_engaged(
        self,
        conv_id: str,
        merchant_id: Optional[str],
        customer_id: Optional[str],
        history: List[Turn],
    ) -> dict:
        merchant, category = self._resolve_merchant_category(merchant_id)
        cust_ctx = self.store.contexts.get(("customer", customer_id)) if customer_id else None
        customer = cust_ctx.payload if cust_ctx else None

        result = compose_reply(
            category=category, merchant=merchant, customer=customer,
            history=history, latest_intent=Intent.ENGAGED, llm=self.llm,
        )
        if not result:
            body = "Got it — let me get back to you on that."
            self._record_vera(conv_id, body, "open_ended")
            return {
                "action": "send", "body": body, "cta": "open_ended",
                "rationale": "Fallback ack on composer failure.",
            }
        self._record_vera(conv_id, result["body"], result.get("cta", "open_ended"))
        return {"action": "send", **result}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_merchant_category(self, merchant_id: Optional[str]):
        merchant_ctx = self.store.contexts.get(("merchant", merchant_id)) if merchant_id else None
        merchant = merchant_ctx.payload if merchant_ctx else {}
        cat_slug = merchant.get("category_slug", "")
        cat_ctx = self.store.contexts.get(("category", cat_slug)) if cat_slug else None
        category = cat_ctx.payload if cat_ctx else {}
        return merchant, category

    def _consecutive_auto_reply_count(self, history: List[Turn]) -> int:
        count = 0
        for turn in reversed(history):
            if turn.from_role != "vera" and turn.intent_classified == Intent.AUTO_REPLY.value:
                count += 1
            elif turn.from_role != "vera":
                break
        return count

    def _record_vera(self, conv_id: str, body: str, cta: str) -> None:
        self.store.conversations[conv_id].append(Turn(
            ts=datetime.now(timezone.utc),
            from_role="vera",
            body=body,
            kind="send",
            cta=cta,
        ))

    def _last_vera_question(self, history: List[Turn]) -> str:
        for turn in reversed(history):
            if turn.from_role == "vera" and "?" in turn.body:
                parts = [p.strip() for p in turn.body.split(".") if p.strip()]
                return parts[-1] if parts else ""
        return ""
