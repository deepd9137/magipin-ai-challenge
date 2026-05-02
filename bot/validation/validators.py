from __future__ import annotations

import json
import re
from typing import Any, Dict, List, NamedTuple, Optional

_URL_RE = re.compile(r"https?://|www\.|\.com/|bit\.ly|tinyurl", re.IGNORECASE)

VALID_CTA = {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}

# Regex: digit sequences with optional comma-separators, optional decimal, optional %
_NUM_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?")


class ValidationResult(NamedTuple):
    valid: bool
    failures: List[str]


def validate(
    body: str,
    cta: str,
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
    prior_bot_bodies: List[str],
) -> ValidationResult:
    """Run all 6 validation checks. Returns (valid, [failure_reasons])."""
    failures: List[str] = []

    # 1. Body length
    if not body or len(body) < 10:
        failures.append("body_too_short")
    if len(body) > 800:
        failures.append("body_too_long")

    # 2. No URLs
    if _URL_RE.search(body):
        failures.append("contains_url")

    # 3. Taboo vocabulary (from pushed CategoryContext)
    taboo_list: List[str] = category.get("voice", {}).get("vocab_taboo", [])
    for word in taboo_list:
        if word.lower() in body.lower():
            failures.append(f"taboo_word:{word}")

    # 4. CTA shape
    if cta not in VALID_CTA:
        failures.append(f"invalid_cta:{cta}")

    # 5. Anti-fabrication
    fab_failures = _check_fabrication(body, category, merchant, trigger, customer)
    failures.extend(fab_failures)

    # 6. No verbatim repetition vs prior bot turns
    norm_body = re.sub(r"\s+", " ", body).strip().lower()
    for prior in prior_bot_bodies:
        prior_norm = re.sub(r"\s+", " ", prior).strip().lower()
        if norm_body == prior_norm:
            failures.append("verbatim_repetition")
            break

    return ValidationResult(valid=(len(failures) == 0), failures=failures)


def _check_fabrication(
    body: str,
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
) -> List[str]:
    """
    Each significant number in the body must appear in the flattened context JSON.
    Handles comma-grouped numbers (2,100 → 2100) and percentage/decimal equivalence.
    """
    flat_raw = " ".join([
        json.dumps(category, ensure_ascii=False),
        json.dumps(merchant, ensure_ascii=False),
        json.dumps(trigger, ensure_ascii=False),
        json.dumps(customer or {}, ensure_ascii=False),
    ]).lower()

    # Normalize: remove commas between digits so "2,100" → "2100" matches "2100"
    flat_norm = re.sub(r"(?<=\d),(?=\d)", "", flat_raw)

    # Normalize body the same way
    body_norm = re.sub(r"(?<=\d),(?=\d)", "", body.lower())

    failures: List[str] = []
    seen: set[str] = set()

    for m in _NUM_RE.finditer(body_norm):
        raw_tok = m.group(0)
        # Strip commas (already done in body_norm) and trailing % for the base value
        clean = raw_tok.replace(",", "")

        if clean in seen:
            continue
        seen.add(clean)

        # Skip trivially small numbers (1 or 2 digits without %)
        base = clean.rstrip("%")
        if len(base) <= 1:
            continue

        # Check literal presence in normalized flat
        if clean in flat_norm:
            continue

        # Also check percentage ↔ decimal equivalence
        if clean.endswith("%"):
            # "38%" → check "38", "0.38", "0.380"
            if base in flat_norm:
                continue
            try:
                fval = float(base) / 100
                if str(fval) in flat_norm or f"{fval:.2f}" in flat_norm:
                    continue
            except ValueError:
                pass
        else:
            # "0.38" → check "38%"
            if clean.startswith("0.") and (clean[2:] + "%") in flat_norm:
                continue

        failures.append(f"unverified_number:{raw_tok.replace(',', '')}")

    # Cap at 2 to avoid drowning out other failure types
    return failures[:2]
