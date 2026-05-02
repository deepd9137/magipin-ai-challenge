# Vera — magicpin AI Challenge

AI-powered WhatsApp merchant engagement bot.

## Approach

4-layer context composition: every outbound message is composed by combining the merchant's category voice profile, their live performance signals, the specific trigger event, and (optionally) the target customer. An LLM generates the message; a validation pipeline strips fabricated data, banned URLs, taboo vocabulary, and malformed CTAs before the message is sent.

## Run

```bash
pip install -r requirements.txt
uvicorn bot.main:app --host 0.0.0.0 --port 8080 --reload
```

## Test

```bash
pytest tests/ -v
```

## Judge simulator

Edit `judge_simulator.py` (set `LLM_PROVIDER`, `LLM_API_KEY`, `BOT_URL`, `TEST_SCENARIO`), then:

```bash
python judge_simulator.py
```
