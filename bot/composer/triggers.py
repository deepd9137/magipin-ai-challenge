from __future__ import annotations

TRIGGER_FRAMINGS: dict[str, str] = {
    "research_digest": (
        "Lead with the single most-relevant research item. Cite source + page/issue number. "
        "Anchor on a merchant-specific signal (their customer_aggregate or signals list) "
        "explaining WHY this study matters to THIS merchant specifically. "
        "Offer to pull the abstract or draft a patient/customer-education message they can reshare."
    ),
    "regulation_change": (
        "Lead with the deadline date and what changes. Cite the issuing body (DCI, FSSAI, etc.). "
        "Estimate impact on this merchant (do they have the equipment/practice affected?). "
        "Offer a concrete next step to check or help comply."
    ),
    "perf_dip": (
        "Diagnose, then reframe. State the dip with exact numbers from the trigger payload. "
        "Contextualize: is it seasonal? peer-wide? merchant-specific? "
        "Propose ONE concrete highest-ROI next step. Do not catastrophize."
    ),
    "perf_spike": (
        "Acknowledge the win with exact numbers. Suggest one capture-the-moment action "
        "(post on GBP, capture a testimonial, share on social). Keep it concise and celebratory."
    ),
    "recall_due": (
        "CUSTOMER-FACING. Lead with timing ('It's been X months'). "
        "Offer 2 specific slots honoring their stated preferences. "
        "State the price + any free-add. Multi-choice slot CTA is appropriate here."
    ),
    "renewal_due": (
        "Show value delivered in the renewing period with concrete numbers from merchant performance. "
        "State the renewal price + what changes if they don't renew. "
        "Single binary CTA — make the decision easy."
    ),
    "festival_upcoming": (
        "Category-specific hook: Salons → bridal/festive looks; Restaurants → festival menu/covers; "
        "Pharmacies → festival-related stock. Lead with days-until + a concrete drafted artifact "
        "or action the merchant can take today."
    ),
    "curious_ask_due": (
        "Ask the merchant a specific, low-stakes question using the Cialdini 'asking' lever. "
        "Frame around what's unique to their week or their data. "
        "Offer clear reciprocity for their answer (I'll turn it into a Google post + reply template). "
        "Respect their time — frame as 5-minute effort."
    ),
    "customer_lapsed_soft": (
        "CUSTOMER-FACING. Warm, no-shame. Reference their past relationship "
        "(services received, time since last visit). Specific new offering relevant to past goals. "
        "No-commitment CTA — low friction."
    ),
    "customer_lapsed_hard": (
        "CUSTOMER-FACING. Same as soft but add a stronger risk-reversal "
        "(free trial, no auto-charge, no commitment). Single binary CTA."
    ),
    "competitor_opened": (
        "Acknowledge calmly, not alarmingly. Pull peer benchmarks for their locality. "
        "Suggest one concrete differentiation play "
        "(review depth, response time, niche service they offer that the competitor does not)."
    ),
    "review_theme_emerged": (
        "Surface the theme with a quote count. Do NOT lecture. "
        "Offer to draft a response template + an operational change suggestion. "
        "Keep the tone collaborative, not critical."
    ),
    "milestone_reached": (
        "Celebrate concretely (the milestone number). Suggest converting it into a "
        "social-proof artifact (testimonial post, GBP update, WhatsApp broadcast). "
        "One concrete action, not a list."
    ),
    "seasonal_perf_dip": (
        "Pre-empt anxiety: this dip is normal and expected. Cite the peer-wide seasonal pattern. "
        "Reframe to retention-focus action. Advise against wasting ad spend during the lull."
    ),
    "supply_alert": (
        "Lead with urgency and specifics (batch numbers, molecule, manufacturer). "
        "Bound the risk clearly (sub-potency vs safety risk). "
        "Pull affected customer count from merchant's customer_aggregate. "
        "Offer end-to-end workflow: customer notification draft + replacement pickup process."
    ),
    "chronic_refill_due": (
        "CUSTOMER-FACING. Name the molecules clearly. State the stock-out date. "
        "Show savings (senior discount, delivery benefit) upfront. "
        "Make the action single-step: one reply to confirm delivery."
    ),
    "gbp_unverified": (
        "Lead with the estimated uplift from verification. "
        "State the two verification paths clearly (postcard or phone call). "
        "Keep it actionable — one step, 10-minute effort framing."
    ),
    "category_seasonal": (
        "Lead with the strongest demand shift (highest % change item). "
        "Recommend a specific shelf action or stock adjustment. "
        "Anchor on peer benchmark data if available in context."
    ),
    "winback_eligible": (
        "Merchant winback — acknowledge the gap tactfully. "
        "Show what the merchant missed (customers added, performance delta). "
        "State the re-activation offer clearly. Single CTA."
    ),
    "dormant_with_vera": (
        "Re-engage the merchant who has gone quiet. "
        "Reference the last topic and offer a fresh, low-friction value-add. "
        "Keep it short — one question or one concrete offer."
    ),
    "active_planning_intent": (
        "The merchant has expressed planning intent. Respond to their EXACT ask. "
        "Provide a complete drafted artifact (menu, package structure, pricing tiers) "
        "they can immediately use. Include specific next-step CTA."
    ),
    "trial_followup": (
        "CUSTOMER-FACING. Reference the trial date. "
        "Offer specific next session slots. Keep it warm and low-pressure. "
        "Single binary confirm CTA."
    ),
    "wedding_package_followup": (
        "CUSTOMER-FACING. Reference the wedding date and trial done. "
        "Calculate days remaining — use it as the urgency anchor. "
        "Offer a specific program with price. Honor preferred slot times."
    ),
    "bridal_followup": (
        "CUSTOMER-FACING. Reference the bridal trial or consultation completed and the upcoming wedding date. "
        "State days remaining to wedding — that is the urgency anchor. "
        "Offer the full bridal package with price and what it includes. "
        "Reference the customer's preferred slot times from context. "
        "Single binary CTA — make booking feel like the natural next step."
    ),
    "ipl_match_today": (
        "Operator intelligence: Saturday/Sunday IPL usually shifts customers to home-viewing "
        "— push delivery-optimized offers, not dine-in. Weeknight matches can drive traffic. "
        "Reference the specific match + venue + time. Leverage existing active offers. "
        "Offer a concrete deliverable (Swiggy banner, Insta story) with time estimate."
    ),
    "cde_opportunity": (
        "Lead with the credit value and free/fee status. "
        "Connect the webinar topic to a specific merchant signal or recent trigger. "
        "Give the registration path without a URL in the body."
    ),
    "perf_dip_merchant": (
        "Diagnose, then reframe. State the dip with exact numbers. "
        "Propose ONE concrete next step with highest ROI."
    ),
}

_DEFAULT_FRAMING = "Compose a relevant, specific message based on the trigger details. Include concrete numbers from context. Single CTA in the last sentence."


def get_framing(trigger_kind: str) -> str:
    """Return trigger framing guide for trigger_kind; falls back to generic if unknown."""
    return TRIGGER_FRAMINGS.get(trigger_kind, _DEFAULT_FRAMING)
