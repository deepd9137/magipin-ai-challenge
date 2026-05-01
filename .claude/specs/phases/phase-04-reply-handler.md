# Phase 4 — Multi-Turn Reply Handler

## Goal
Replace the `/v1/reply` stub with a full conversation handler that detects merchant intent (auto-reply, opt-out, hostile, intent-commit, off-topic, engaged) and produces the right response: `send`, `wait`, or `end`. This phase delivers the **conversational intelligence** that distinguishes a good bot from a great one in the judge's replay tests.

---

## Why this phase next
The 4 highest-impact judge penalties live in this phase:
1. **Auto-reply burning** — production Vera burns 2–3 turns on canned auto-replies. The judge explicitly tests this with the `auto_reply_hell` scenario.
2. **Intent-handoff failure** — production Vera asks qualifying questions after a merchant says "yes let's do it". The judge tests this with `intent_transition`.
3. **Hostile mishandling** — bots that don't gracefully exit on opt-out lose points fast.
4. **Off-topic derailing** — bots that answer "help me file my GST" lose thread coherence.

This is also the phase that gates entry to the top-10 replay round. Bots that don't pass these scenarios won't get the +30 replay bonus, no matter how good their compositions are.

---

## Capabilities Delivered

1. **Conversation state tracking** — every `/v1/reply` appends a `Turn` to `conversations[conv_id]`. Bot has full history available for classifier.

2. **Intent classifier** — given the latest message + conversation history, classify into one of 7 intents:
   - `AUTO_REPLY` — canned WhatsApp Business response
   - `OPT_OUT` — explicit "stop messaging me"
   - `HOSTILE` — abusive or strongly negative
   - `INTENT_COMMIT` — "yes let's do it", "go ahead"
   - `OFF_TOPIC` — unrelated ask
   - `ENGAGED` — genuine reply progressing the conversation
   - `UNCLEAR` — ambiguous; treat as engaged

3. **Per-intent action handlers**:
   - AUTO_REPLY: send hint (turn 1) → wait (turn 2) → end (turn 3+)
   - OPT_OUT/HOSTILE: end immediately, mark conv ended
   - INTENT_COMMIT: skip qualifying; compose action-mode response (concrete next step + binary confirm CTA)
   - OFF_TOPIC: polite decline + redirect back to original thread
   - ENGAGED: continue conversation via reply-mode composer

4. **Reply-mode composer** — variant of Phase 3 composer that takes conversation history as additional input and produces context-aware follow-ups.

5. **Ended-conversation guard** — once a conv_id is in `ended_conversations`, any subsequent `/v1/reply` for it returns a no-op without invoking LLM.

6. **Auto-reply detection heuristics**:
   - Phrase matchers (regex): "thank you for contacting", "team will respond shortly", "automated assistant", "this is an automated", "please leave a message"
   - Repetition signal: same body verbatim ≥ 2 times in conversation
   - Combined classification: phrase OR (repetition AND short generic message)

7. **Intent commit detection**:
   - Affirmative phrases: "yes", "ok", "let's do it", "go ahead", "haan", "kar do", "send", "draft it"
   - Combined with prior Vera turn — only classify as commit if last bot turn asked an actionable yes/no question

---

## Files / Modules to Implement

```
bot/
├── intent/
│   ├── __init__.py
│   ├── classifier.py              # classify(message, history) → Intent
│   ├── patterns.py                # regex / phrase lists per intent
│   └── llm_classifier.py          # fallback: LLM-based classification when patterns inconclusive
├── composer/
│   └── reply_composer.py          # compose_reply(category, merchant, history, latest, intent)
├── services/
│   └── reply_service.py           # ReplyService.handle() — full state machine
└── state.py                       # Turn dataclass; helpers for history slices

tests/
├── test_intent_patterns.py        # unit tests for each pattern type
├── test_intent_classifier.py      # full classify() with history scenarios
├── test_reply_service.py          # state machine: each intent → correct action
├── test_auto_reply_state.py       # 3-turn progression: hint → wait → end
└── test_intent_commit_state.py    # commit only when prior bot asked actionable question
```

### `bot/intent/patterns.py`
```python
import re

AUTO_REPLY_PHRASES = [
    r"thank you for contacting",
    r"team will (?:respond|get back|reach out)",
    r"automated (?:assistant|reply|response)",
    r"this is an automated",
    r"please leave a (?:message|name)",
    r"hamari team (?:tak|aap se)",
    r"jaankari ke liye .* shukriya",
    r"out of office",
    r"will respond shortly",
]

OPT_OUT_PHRASES = [
    r"stop (?:messag|sending|spamm)",
    r"unsubscribe",
    r"don'?t (?:message|contact|call)",
    r"leave me alone",
    r"not interested.*(?:stop|don'?t)",
    r"band karo",
    r"mat bhejo",
]

HOSTILE_PHRASES = [
    r"\b(?:useless|bothering|harass|spam|annoying)\b",
    r"\b(?:stupid|idiotic|nonsense|bakwas|bekar)\b",
    r"why are you (?:bothering|messaging)",
]

COMMIT_PHRASES = [
    r"^(?:yes|haan|ok|okay|sure|yep)\b.*(?:please|kar do|do it|go ahead|send|draft)",
    r"let'?s do (?:it|this)",
    r"(?:go|chal) (?:ahead|kar)",
    r"^(?:yes|haan|ok|okay)\.?$",          # bare yes only with prior actionable question
    r"draft (?:it|kar|karo)",
    r"send (?:it|kar)",
    r"proceed",
    r"confirm",
]

OFF_TOPIC_KEYWORDS = [
    "gst", "tax filing", "loan", "credit card", "stock market",
    "weather", "cricket", "movie", "personal",
]

def matches_any(message: str, patterns: list[str]) -> bool:
    msg = message.lower()
    return any(re.search(p, msg, re.I) for p in patterns)
```

### `bot/intent/classifier.py`
```python
from enum import Enum
from .patterns import (
    AUTO_REPLY_PHRASES, OPT_OUT_PHRASES, HOSTILE_PHRASES,
    COMMIT_PHRASES, OFF_TOPIC_KEYWORDS, matches_any
)

class Intent(str, Enum):
    AUTO_REPLY = "auto_reply"
    OPT_OUT = "opt_out"
    HOSTILE = "hostile"
    INTENT_COMMIT = "intent_commit"
    OFF_TOPIC = "off_topic"
    ENGAGED = "engaged"
    UNCLEAR = "unclear"

def classify(message: str, history: list[dict]) -> Intent:
    msg = message.strip()

    # 1. Hostile (check before opt-out — opt-out can co-occur with hostile)
    if matches_any(msg, HOSTILE_PHRASES):
        return Intent.HOSTILE

    # 2. Opt-out (explicit stop)
    if matches_any(msg, OPT_OUT_PHRASES):
        return Intent.OPT_OUT

    # 3. Auto-reply (phrase match OR exact-repetition signal)
    if matches_any(msg, AUTO_REPLY_PHRASES):
        return Intent.AUTO_REPLY
    # Repetition check: same merchant message verbatim ≥ 2 times
    merchant_msgs = [t["body"] for t in history if t.get("from_role") == "merchant"]
    if merchant_msgs.count(msg) >= 2 and len(msg) < 200:
        return Intent.AUTO_REPLY

    # 4. Intent commit — bare "yes" only counts if prior Vera turn was actionable
    if matches_any(msg, COMMIT_PHRASES):
        if _last_bot_asked_actionable(history):
            return Intent.INTENT_COMMIT
        # bare "yes" without prior actionable question → engaged, not commit

    # 5. Off-topic — keyword + question shape, NOT during active commitment thread
    if any(kw in msg.lower() for kw in OFF_TOPIC_KEYWORDS) and "?" in msg:
        return Intent.OFF_TOPIC

    # 6. Default: engaged
    if msg:
        return Intent.ENGAGED
    return Intent.UNCLEAR


def _last_bot_asked_actionable(history: list[dict]) -> bool:
    for turn in reversed(history):
        if turn.get("from_role") == "vera":
            body = turn.get("body", "").lower()
            return any(s in body for s in ["want me to", "shall i", "should i",
                                            "draft", "send", "schedule",
                                            "kya draft", "bhej dun"])
    return False
```

### `bot/services/reply_service.py`
```python
from datetime import datetime
from ..intent.classifier import classify, Intent
from ..composer.reply_composer import compose_reply
from ..state import store, Turn

class ReplyService:
    def __init__(self, llm):
        self.llm = llm

    def handle(self, conv_id: str, merchant_id: str | None, customer_id: str | None,
               from_role: str, message: str, turn_number: int) -> dict:
        # Hard guard: ended conversations
        if conv_id in store.ended_conversations:
            return {"action": "end", "rationale": "conversation already ended; ignoring"}

        history = store.conversations.setdefault(conv_id, [])

        # Classify BEFORE appending — classifier needs prior history shape
        intent = classify(message, history)

        # Append current turn
        turn = Turn(ts=datetime.utcnow(), from_role=from_role, body=message,
                    kind="reply", intent_classified=intent.value)
        history.append(turn.__dict__)

        # Route by intent
        if intent == Intent.AUTO_REPLY:
            return self._handle_auto_reply(conv_id, history)
        if intent in (Intent.OPT_OUT, Intent.HOSTILE):
            return self._handle_exit(conv_id, intent)
        if intent == Intent.INTENT_COMMIT:
            return self._handle_commit(conv_id, merchant_id, history)
        if intent == Intent.OFF_TOPIC:
            return self._handle_off_topic(conv_id, merchant_id, history)
        # ENGAGED or UNCLEAR
        return self._handle_engaged(conv_id, merchant_id, customer_id, history)

    def _handle_auto_reply(self, conv_id, history) -> dict:
        # count consecutive auto-reply turns from merchant
        consecutive = 0
        for turn in reversed(history):
            if turn["from_role"] == "merchant" and turn.get("intent_classified") == "auto_reply":
                consecutive += 1
            elif turn["from_role"] == "merchant":
                break
        if consecutive == 1:
            body = ("Looks like an auto-reply 😊 When the owner sees this, "
                    "just reply YES to continue.")
            self._record_bot_turn(conv_id, body)
            return {"action": "send", "body": body, "cta": "binary_yes_no",
                    "rationale": "Detected auto-reply; one explicit prompt to flag for owner."}
        if consecutive == 2:
            return {"action": "wait", "wait_seconds": 14400,
                    "rationale": "Same auto-reply twice; backing off 4h for owner to see."}
        # 3+
        store.ended_conversations.add(conv_id)
        return {"action": "end",
                "rationale": "Auto-reply 3x consecutive; closing conversation."}

    def _handle_exit(self, conv_id, intent) -> dict:
        store.ended_conversations.add(conv_id)
        if intent == Intent.HOSTILE:
            return {"action": "end",
                    "rationale": "Merchant frustration explicit; closing without further engagement."}
        return {"action": "end",
                "rationale": "Merchant explicitly opted out; closing conversation."}

    def _handle_commit(self, conv_id, merchant_id, history) -> dict:
        merchant = store.contexts.get(("merchant", merchant_id))
        category = store.contexts.get(("category", merchant.payload.get("category_slug"))) if merchant else None
        result = compose_reply(category=category.payload if category else {},
                               merchant=merchant.payload if merchant else {},
                               history=history, latest_intent=Intent.INTENT_COMMIT,
                               llm=self.llm)
        if not result:
            return {"action": "send", "body": "On it. Drafting now — 90 seconds.",
                    "cta": "binary_confirm_cancel",
                    "rationale": "Commit detected; minimal action ack."}
        self._record_bot_turn(conv_id, result["body"])
        return {"action": "send", **result,
                "rationale": result.get("rationale", "Commit detected; switched to action mode.")}

    def _handle_off_topic(self, conv_id, merchant_id, history) -> dict:
        # Polite decline + redirect to last open thread
        body = ("That's outside what I can help with — your CA or the relevant "
                "service is the right route. Coming back to our thread — ")
        # append last bot question if available
        last_q = self._last_bot_question(history)
        if last_q:
            body += last_q
        else:
            body += "want to continue from where we paused?"
        self._record_bot_turn(conv_id, body)
        return {"action": "send", "body": body, "cta": "open_ended",
                "rationale": "Out-of-scope ask politely declined; redirected to original thread."}

    def _handle_engaged(self, conv_id, merchant_id, customer_id, history) -> dict:
        merchant = store.contexts.get(("merchant", merchant_id)) if merchant_id else None
        category = (store.contexts.get(("category", merchant.payload.get("category_slug")))
                    if merchant else None)
        customer = store.contexts.get(("customer", customer_id)) if customer_id else None

        result = compose_reply(
            category=category.payload if category else {},
            merchant=merchant.payload if merchant else {},
            customer=customer.payload if customer else None,
            history=history, latest_intent=Intent.ENGAGED, llm=self.llm,
        )
        if not result:
            return {"action": "send", "body": "Got it — let me get back to you on that.",
                    "cta": "open_ended", "rationale": "Fallback ack on composer failure."}
        self._record_bot_turn(conv_id, result["body"])
        return {"action": "send", **result}

    def _record_bot_turn(self, conv_id, body):
        store.conversations[conv_id].append(Turn(
            ts=datetime.utcnow(), from_role="vera", body=body, kind="send"
        ).__dict__)

    def _last_bot_question(self, history) -> str:
        for turn in reversed(history):
            if turn["from_role"] == "vera" and "?" in turn.get("body", ""):
                return turn["body"].split(".")[-1].strip()
        return ""
```

### `bot/composer/reply_composer.py` (sketch)
```python
def compose_reply(category, merchant, history, latest_intent, llm,
                  customer=None) -> dict | None:
    """Variant of compose() that includes conversation history in the prompt."""
    history_text = "\n".join([
        f"[{turn['from_role']}] {turn['body']}" for turn in history[-6:]
    ])

    system = build_reply_system(category, latest_intent)
    user = (f"=== CONVERSATION SO FAR ===\n{history_text}\n\n"
            f"=== MERCHANT CONTEXT ===\n{summarize(merchant)}\n\n"
            f"Latest intent: {latest_intent.value}\n"
            f"Compose the next bot turn. JSON only.")

    raw = llm.complete(system, user, timeout=20)
    return parse_and_validate(raw, category, merchant, history)
```

---

## Test Plan

### Pattern unit tests
1. `test_auto_reply_phrase_thank_you` — "Thank you for contacting us" → AUTO_REPLY
2. `test_auto_reply_phrase_hindi` — "Hamari team aap se sampark karegi" → AUTO_REPLY
3. `test_opt_out_stop_messaging` — "Stop messaging me" → OPT_OUT
4. `test_hostile_detection` — "this is useless spam" → HOSTILE
5. `test_commit_with_prior_actionable` — Vera asked "Want me to draft it?", merchant says "yes please" → INTENT_COMMIT
6. `test_commit_without_actionable` — bare "yes" with no prior actionable question → ENGAGED (not commit)
7. `test_off_topic_gst` — "Can you help me with GST?" → OFF_TOPIC
8. `test_engaged_fallback` — "Tell me more about it" → ENGAGED

### Repetition detection tests
9. `test_repetition_signals_auto_reply` — same short message 2× → AUTO_REPLY even without phrase match

### State machine tests (full ReplyService)
10. `test_auto_reply_progression` — turn 1 sends hint, turn 2 sends wait, turn 3 sends end
11. `test_opt_out_ends_immediately` — first call returns end; conv added to ended_conversations
12. `test_ended_conversation_no_op` — second call to ended conv returns end without LLM
13. `test_commit_switches_to_action_mode` — bot output contains action verb (draft/send/schedule), no qualifying questions
14. `test_off_topic_redirect_includes_prior_question` — bot output contains words from the last bot question

### Integration / replay tests (real LLM)
15. `test_auto_reply_hell_scenario` — judge_simulator.py with TEST_SCENARIO="auto_reply_hell" → all turns pass
16. `test_intent_transition_scenario` — judge_simulator.py with TEST_SCENARIO="intent_transition" → bot correctly switched
17. `test_hostile_scenario` — judge_simulator.py with TEST_SCENARIO="hostile" → bot ends gracefully

---

## Expected Output

### Auto-reply hell — 4-turn replay
```
Turn 2 (merchant auto-reply): "Thank you for contacting Dr. Meera's clinic..."
Bot:  { "action": "send",
        "body": "Looks like an auto-reply 😊 When the owner sees this, just reply YES.",
        "cta": "binary_yes_no" }

Turn 3 (same auto-reply): "Thank you for contacting Dr. Meera's clinic..."
Bot:  { "action": "wait", "wait_seconds": 14400 }

Turn 4 (same auto-reply): "Thank you for contacting Dr. Meera's clinic..."
Bot:  { "action": "end" }
```

### Intent transition replay
```
Turn 1 (Vera): "...Want me to pull the abstract + draft a patient WhatsApp?"
Turn 2 (merchant): "Ok let's do it. What's next?"
Bot:  { "action": "send",
        "body": "On it — abstract attached, drafting your patient WhatsApp now (90s).
                I'll also pre-fill a GBP post for tomorrow 10am. Reply CONFIRM
                to send the draft to your high-risk patient list (124 patients).",
        "cta": "binary_confirm_cancel",
        "rationale": "Commit detected; switched from question-asking to action with 
                       concrete next step + measurable scope." }
```

### Hostile replay
```
Turn 2 (merchant): "Why are you bothering me. This is useless spam."
Bot:  { "action": "end",
        "rationale": "Merchant frustration explicit; closing without further engagement." }
```

### Off-topic redirect
```
Turn 2 (merchant): "Btw can you also help me with GST filing?"
Bot:  { "action": "send",
        "body": "That's outside what I can help with — your CA is the right route.
                Coming back to our thread — want me to pull the abstract + draft 
                the patient WhatsApp?",
        "cta": "open_ended" }
```

---

## Dependencies (prior phases)
- **Phase 1** — state store with `conversations` and `ended_conversations`
- **Phase 2** — LLM adapter
- **Phase 3** — voice packs, validators (reused in reply composer)

---

## Acceptance / Definition of Done

- [ ] All 7 intents distinguishable by classifier
- [ ] Pattern matchers tested in English + Hindi-English mix
- [ ] Auto-reply progression: hint → wait → end across 3 consecutive turns
- [ ] Intent commit only fires when prior bot asked actionable question
- [ ] Opt-out and hostile both end immediately and mark conv ended
- [ ] Ended conversations short-circuit without invoking LLM
- [ ] Off-topic produces a redirect that references the prior thread
- [ ] All 17 tests pass
- [ ] `judge_simulator.py auto_reply_hell` → all turns pass
- [ ] `judge_simulator.py intent_transition` → bot output contains action verbs, no qualifying questions
- [ ] `judge_simulator.py hostile` → bot ends within 1 turn

---

## Estimated Effort
~10–12 hours: pattern tuning is iterative (false positives on bare "yes" / "ok" are tricky), reply composer needs separate prompt, state machine has many branches.
