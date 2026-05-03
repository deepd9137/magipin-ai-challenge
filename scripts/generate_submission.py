"""
Build submission.jsonl from the canonical 30 test pairs.

Usage (from project root):
    python scripts/generate_submission.py \\
        --pairs scripts/canonical_test_pairs.json \\
        --output submission.jsonl \\
        --dataset-dir dataset

    # Resume a partial run (skip already-successful entries):
    python scripts/generate_submission.py ... --resume
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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


def _load_existing(path: str) -> dict[str, dict]:
    """Load existing output; keep only non-failed entries keyed by test_id."""
    p = Path(path)
    if not p.exists():
        return {}
    keep: dict[str, dict] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Only keep successful (no compose_failed reason) or consent-skipped entries
        if not entry.get("skipped") or entry.get("reason") != "compose_failed":
            keep[entry["test_id"]] = entry
    return keep


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


def _build_llm(provider: str, key: str, model: str):
    if provider == "anthropic":
        from bot.llm.anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(api_key=key, model=model)
    elif provider == "gemini":
        from bot.llm.gemini_adapter import GeminiAdapter
        return GeminiAdapter(api_key=key, model=model)
    elif provider == "openai":
        from bot.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(api_key=key, model=model)
    elif provider == "nvidia":
        from bot.llm.nvidia_adapter import NvidiaAdapter
        return NvidiaAdapter(api_key=key, model=model)
    else:
        print(f"ERROR: unsupported LLM_PROVIDER={provider!r}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate submission.jsonl")
    parser.add_argument("--pairs", required=True, help="Path to canonical_test_pairs.json")
    parser.add_argument("--output", default="submission.jsonl")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to sleep between LLM calls (default 2.0)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip test_ids that already have a successful entry in --output")
    args = parser.parse_args()

    dataset = load_dataset(Path(args.dataset_dir))
    pairs: list[dict] = json.loads(Path(args.pairs).read_text())

    llm = _build_llm(settings.llm_provider, settings.llm_api_key, settings.llm_model)
    print(f"LLM: {settings.llm_provider}:{settings.llm_model}")

    # Load existing results if resuming
    existing: dict[str, dict] = _load_existing(args.output) if args.resume else {}
    if existing:
        print(f"Resume: {len(existing)} existing entries loaded (will skip these)")

    results: dict[str, dict] = dict(existing)

    written = 0
    skipped = 0
    failed = 0
    resumed = 0

    for pair in pairs:
        test_id = pair["test_id"]
        merchant_id = pair["merchant_id"]
        trigger_id = pair["trigger_id"]

        if test_id in existing:
            print(f"SKIP [{test_id}] already done")
            resumed += 1
            continue

        merchant = dataset["merchants"].get(merchant_id)
        if not merchant:
            print(f"WARN [{test_id}] merchant {merchant_id!r} not found — skipping", file=sys.stderr)
            results[test_id] = {"test_id": test_id, "skipped": True, "reason": "merchant_not_found"}
            skipped += 1
            continue

        trigger = dataset["triggers"].get(trigger_id)
        if not trigger:
            print(f"WARN [{test_id}] trigger {trigger_id!r} not found — skipping", file=sys.stderr)
            results[test_id] = {"test_id": test_id, "skipped": True, "reason": "trigger_not_found"}
            skipped += 1
            continue

        category = dataset["categories"].get(merchant["category_slug"])
        if not category:
            print(f"WARN [{test_id}] category {merchant['category_slug']!r} not found — skipping", file=sys.stderr)
            results[test_id] = {"test_id": test_id, "skipped": True, "reason": "category_not_found"}
            skipped += 1
            continue

        customer_id = trigger.get("customer_id")
        customer = dataset["customers"].get(customer_id) if customer_id else None

        if customer_id and not has_consent(customer or {}, trigger.get("kind", "")):
            print(f"INFO [{test_id}] consent missing for {customer_id} / {trigger.get('kind')} — skipping")
            results[test_id] = {"test_id": test_id, "skipped": True, "reason": "consent_missing"}
            skipped += 1
            continue

        if customer:
            result = compose_customer_facing(category, merchant, trigger, customer, llm)
        else:
            result = compose(category, merchant, trigger, customer=None, llm=llm)

        if not result:
            print(f"WARN [{test_id}] composition returned None — skipping", file=sys.stderr)
            results[test_id] = {"test_id": test_id, "skipped": True, "reason": "compose_failed"}
            failed += 1
        else:
            action = _build_action(test_id, merchant, customer, trigger, result)
            results[test_id] = action
            written += 1
            print(f"OK  [{test_id}] {merchant_id} / {trigger_id} — {len(result.body)} chars")

        if args.delay > 0:
            time.sleep(args.delay)

    # Write output in canonical pair order
    pair_order = [p["test_id"] for p in pairs]
    with open(args.output, "w", encoding="utf-8") as out_f:
        for tid in pair_order:
            if tid in results:
                out_f.write(json.dumps(results[tid], ensure_ascii=False) + "\n")

    total = written + skipped + failed + resumed
    print(f"\nDone: {written} composed, {skipped} skipped, {failed} failed, {resumed} resumed — {total} total")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
