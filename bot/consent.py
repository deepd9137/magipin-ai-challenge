from __future__ import annotations

TRIGGER_KIND_TO_CONSENT_SCOPE: dict[str, str] = {
    "recall_due": "recall_reminders",
    "appointment_tomorrow": "appointment_reminders",
    "appointment_reminder": "appointment_reminders",
    "chronic_refill_due": "medication_reminders",
    "wedding_package_followup": "marketing_outreach",
    "bridal_followup": "marketing_outreach",
    "customer_lapsed_soft": "marketing_outreach",
    "customer_lapsed_hard": "marketing_outreach",
    "promotional_campaign": "promotional_outreach",
}


def has_consent(customer: dict, trigger_kind: str) -> bool:
    """Return True if the customer has consented to receive this trigger kind.

    Merchant-facing triggers (customer=None) always pass.
    """
    if not customer:
        return True

    required = TRIGGER_KIND_TO_CONSENT_SCOPE.get(trigger_kind)
    if not required:
        # No specific mapping — allow only if customer has opted in to anything at all.
        return bool(customer.get("consent", {}).get("scope"))

    return required in customer.get("consent", {}).get("scope", [])
