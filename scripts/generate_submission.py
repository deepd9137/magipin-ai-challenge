"""
Build submission.jsonl from the canonical 30 test pairs.

Usage (from project root):
    python scripts/generate_submission.py \\
        --pairs scripts/canonical_test_pairs.json \\
        --output submission.jsonl \\
        --dataset-dir dataset
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.composer.composer import compose
from bot.composer.customer_composer import compose_customer_facing
from bot.config import settings
from bot.consent import has_consent


def load_dataset(root: Path) -> dict:
    out: dict = {"categories": {}, "merchants": {}, "customers": {}, "triggers": {}}
    for f in sorted((root / "categories").glob("*.json")):
        d = json.loads(f.read_text())
        out["categories"][d["slug"]] = d
    for entry in json.loads((root / "merchants_seed.json").read_text())["merchants"]:
        out["merchants"][entry["merchant_id"]] = entry
    for entry in json.loads((root / "customers_seed.json").read_text()).get("customers", []):
        out["customers"][entry["customer_id"]] = entry
    for entry in json.loads((root / "triggers_seed.json").read_text())["triggers"]:
        out["triggers"][entry["id"]] = entry
    return out


def _build_action(test_id: str, merchant: dict, customer: dict | None,
                  trigger: dict, msg) -> dict:
    return {
        "test_id": test_id,
        "merchant_id": merchant["merchant_id"],
        "customer_id": customer["customer_id"] if customer else None,
        "trigger_id": trigger["id"],
        "send_as": msg.send_as,
        "body": msg.body,
        "cta": msg.cta,
        "template_name": msg.template_name,
        "template_params": msg.template_params,
        "suppression_key": msg.suppression_key,
        "rationale": msg.rationale,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate submission.jsonl")
    parser.add_argument("--pairs", required=True, help="Path to canonical_test_pairs.json")
    parser.add_argument("--output", default="submission.jsonl")
    parser.add_argument("--dataset-dir", default="dataset")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset_dir))
    pairs: list[dict] = json.loads(Path(args.pairs).read_text())

    # Build LLM adapter from current settings
    if settings.llm_provider == "anthropic":
        from bot.llm.anthropic_adapter import AnthropicAdapter
        llm = AnthropicAdapter(api_key=settings.llm_api_key, model=settings.llm_model)
    elif settings.llm_provider == "gemini":
        from bot.llm.gemini_adapter import GeminiAdapter
        llm = GeminiAdapter(api_key=settings.llm_api_key, model=settings.llm_model)
    elif settings.llm_provider == "openai":
        from bot.llm.openai_adapter import OpenAIAdapter
        llm = OpenAIAdapter(api_key=settings.llm_api_key, model=settings.llm_model)
    else:
        print(f"ERROR: unsupported LLM_PROVIDER={settings.llm_provider!r}", file=sys.stderr)
        sys.exit(1)

    written = 0
    skipped = 0
    failed = 0

    with open(args.output, "w", encoding="utf-8") as out_f:
        for pair in pairs:
            test_id = pair["test_id"]
            merchant_id = pair["merchant_id"]
            trigger_id = pair["trigger_id"]

            merchant = dataset["merchants"].get(merchant_id)
            if not merchant:
                print(f"WARN [{test_id}] merchant {merchant_id!r} not found — skipping", file=sys.stderr)
                line = {"test_id": test_id, "skipped": True, "reason": "merchant_not_found"}
                out_f.write(json.dumps(line, ensure_ascii=False) + "\n")
                skipped += 1
                continue

            trigger = dataset["triggers"].get(trigger_id)
            if not trigger:
                print(f"WARN [{test_id}] trigger {trigger_id!r} not found — skipping", file=sys.stderr)
                line = {"test_id": test_id, "skipped": True, "reason": "trigger_not_found"}
                out_f.write(json.dumps(line, ensure_ascii=False) + "\n")
                skipped += 1
                continue

            category = dataset["categories"].get(merchant["category_slug"])
            if not category:
                print(f"WARN [{test_id}] category {merchant['category_slug']!r} not found — skipping", file=sys.stderr)
                line = {"test_id": test_id, "skipped": True, "reason": "category_not_found"}
                out_f.write(json.dumps(line, ensure_ascii=False) + "\n")
                skipped += 1
                continue

            customer_id = trigger.get("customer_id")
            customer = dataset["customers"].get(customer_id) if customer_id else None

            # Consent gate for customer-scoped triggers
            if customer_id and not has_consent(customer or {}, trigger.get("kind", "")):
                print(f"INFO [{test_id}] consent missing for {customer_id} / {trigger.get('kind')} — skipping")
                line = {"test_id": test_id, "skipped": True, "reason": "consent_missing"}
                out_f.write(json.dumps(line, ensure_ascii=False) + "\n")
                skipped += 1
                continue

            if customer:
                result = compose_customer_facing(category, merchant, trigger, customer, llm)
            else:
                result = compose(category, merchant, trigger, customer=None, llm=llm)

            if not result:
                print(f"WARN [{test_id}] composition returned None — skipping", file=sys.stderr)
                line = {"test_id": test_id, "skipped": True, "reason": "compose_failed"}
                out_f.write(json.dumps(line, ensure_ascii=False) + "\n")
                failed += 1
                continue

            action = _build_action(test_id, merchant, customer, trigger, result)
            out_f.write(json.dumps(action, ensure_ascii=False) + "\n")
            written += 1
            print(f"OK  [{test_id}] {merchant_id} / {trigger_id} — {len(result.body)} chars")

    total = written + skipped + failed
    print(f"\nDone: {written} composed, {skipped} skipped (consent/missing), {failed} failed — {total} total")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
