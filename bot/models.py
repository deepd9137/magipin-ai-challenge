from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


VALID_SCOPES = {"category", "merchant", "customer", "trigger"}
VALID_CTA = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}


# ── Inbound request bodies ─────────────────────────────────────────────────

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class TickBody(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: Optional[str] = None
    turn_number: int = 1


# ── Outbound response shapes ───────────────────────────────────────────────

class ActionItem(BaseModel):
    conversation_id: str
    merchant_id: Optional[str]
    customer_id: Optional[str]
    send_as: str
    trigger_id: str
    template_name: str
    template_params: List[str]
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[ActionItem]


class ReplyResponse(BaseModel):
    action: str                     # "send" | "wait" | "end"
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str = ""
