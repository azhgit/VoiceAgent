# Voice Agent POC

A Twilio-connected voice agent for after-hours plumbing/HVAC dispatch: it
answers a real phone call, classifies the caller's problem, checks a mock
CRM for open appointment slots, and books one — or simulates a transfer to
a live dispatcher when the situation calls for it. Built as a job-application
demo; see [CONTEXT.md](CONTEXT.md) for the scenario and domain language, and
[doc/voice-agent-poc-plan.md](doc/voice-agent-poc-plan.md) for the original
execution plan this was built against.

## Why this exists

The target role evaluates hands-on ownership of a real-time voice pipeline —
conversation quality, latency, reliability, and integration with a business
system — not the ability to assemble a managed product. So this deliberately
hand-builds the pipeline on [Pipecat](https://github.com/pipecat-ai/pipecat)
instead of a fully managed voice-agent platform. See
[docs/adr/0001-pipecat-not-managed-platform.md](docs/adr/0001-pipecat-not-managed-platform.md)
for the full reasoning.

## Architecture

```
Twilio Media Streams (8kHz mulaw)
  → Pipecat pipeline
      → Deepgram (Nova-3) STT
      → SilenceTimeoutProcessor   (Day 3: caller-silence check-in / hangup)
      → Claude (tool calling)     (Day 1: dispatch logic, reads/writes the CRM)
      → ElevenLabs (Flash v2.5) streaming TTS
  → back to Twilio
```

Interruption handling (barge-in) needed no custom code: Pipecat's default
VAD-based turn strategy already treats the caller starting to speak as a
hard stop — it discards whatever the bot was mid-saying rather than
buffering it for resume. See the comment above `LLMContextAggregatorPair` in
[agent/bot.py](agent/bot.py) for the exact source this claim is based on.

Claude reaches the mock CRM (`crm/`, a small FastAPI + SQLAlchemy service)
through three tools, defined once in `agent/bot.py`'s `build_tool_schemas()`
and shared by both the live pipeline and the eval scripts below:

| Tool | Calls | Purpose |
|---|---|---|
| `check_availability` | `GET /availability` | Open slots for a specialty + urgency, excluding already-booked ones |
| `book_appointment` | `POST /appointments` | Books a slot; the CRM rejects (409) a double-booking of the same technician/slot |
| `transfer_and_end_call` | — | Speaks one of two fixed lines, then ends the call (the "Handoff simulation" from CONTEXT.md — no real telephony transfer happens) |

## Dispatch logic

The system prompt (`SYSTEM_INSTRUCTION` in `agent/bot.py`) encodes fixed
classification rules rather than leaving judgment calls to the model:

- **Specialty**: `plumbing` for water/pipe/drain/water-heater issues,
  `hvac` for heating/cooling/air issues.
- **Urgency** (the *Urgent case* / *Non-urgent case* from CONTEXT.md):
  active water damage, no heat near freezing, a gas smell, or sewage
  backup are urgent; a dripping faucet, no hot water, unusual noise, or
  routine maintenance are not.
- **Unclear speech**: ask the caller to repeat once; still unclear on the
  second attempt → *Handoff simulation*.
- **No slot available**: urgent → *Handoff simulation* immediately;
  non-urgent → *Callback promise* (offer to call back, no transfer).

These rules — plus the model's actual tool-calling behavior — are checked
against the real Anthropic API, not just read by eye. See **Testing** below.

## Engineering decisions backed by data, not just defaults

- **Model choice (Haiku, not Sonnet)**: `agent/eval_dispatch_classification.py`
  runs 8 fixed dispatch scenarios against both models over the real API,
  checking tool-call correctness and time-to-first-token. It caught a real
  bug — Haiku classified "no hot water" as `hvac` instead of `plumbing` —
  which was fixed by tightening the specialty rule. After the fix, Haiku
  matches Sonnet's 8/8 accuracy at roughly 1.5–3x lower TTFT, which is why
  Haiku is the default (`ANTHROPIC_MODEL` in `.env.example`) and Sonnet is
  a manual fallback, not a runtime choice.
- **Latency instrumentation**: `agent/latency_observer.py`'s
  `LatencyLogObserver` persists Pipecat's own STT/LLM/TTS TTFB/TTFA metrics
  to `agent/latency_log.jsonl` (one JSON line per stage per turn) instead of
  only printing them to the console, so there's a record to chart from —
  see `agent/visualize_latency.py`.
- **VAD tuning knobs, not tuned values**: `VAD_CONFIDENCE` /
  `VAD_START_SECS` / `VAD_STOP_SECS` env vars let turn-taking sensitivity be
  adjusted without a code change. The values themselves are still Silero's
  generic-mic defaults — real tuning needs a live call pass this POC hasn't
  done yet (see **What's not done**).

## Project layout

```
agent/   - Pipecat voice pipeline (bot.py) + its supporting modules and eval scripts
crm/     - Mock FastAPI CRM (technicians, appointments, availability) + pytest suite
doc/     - Original execution plan (Traditional Chinese)
docs/adr/- Architecture decision records
```

## Running it locally

```bash
# CRM
cd crm
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python seed.py              # 3 technicians, 7 seeded appointments
.venv/bin/uvicorn main:app --port 8000

# Agent (separate shell)
cd agent
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env            # fill in real API keys
.venv/bin/python bot.py
```

For a real call, tunnel the agent's WebSocket endpoint with ngrok and point
a Twilio phone number's webhook at it — not yet done, see below.

## Testing

- **CRM** (`crm/`, deterministic logic — availability filtering, booking
  conflict checks): a real pytest suite, `pytest -q` → 13 passed.
- **Agent dispatch logic** (`agent/`, LLM-driven — not meaningfully
  unit-testable): two eval scripts that call the real Anthropic API:
  - `eval_dispatch_classification.py` — 8 scenarios, model comparison (see above)
  - `eval_edge_cases.py` — 4 multi-turn scenarios verifying the
    unclear-speech and no-slot branches actually call the right tool
- **`SilenceTimeoutProcessor`**: verified against a real minimal Pipecat
  pipeline (not synthetic frames) — check-in fires on timeout, resets on
  caller speech, prolonged silence escalates to a goodbye + hangup.

None of this replaces an actual phone call. See below.

## What's not done

- **A real phone call.** Every piece above has been verified in isolation —
  the CRM against itself, the dispatch logic against the real LLM API, the
  silence timeout against a real (but transport-less) pipeline — but nothing
  has gone through Twilio + Deepgram + ElevenLabs end-to-end yet. That needs
  a live call, which needs a human on a phone.
- **VAD threshold tuning.** The knobs exist; the values are still defaults.
- **Demo recording and latency chart with real data** — `visualize_latency.py`
  works against synthetic data; it needs a real call's `latency_log.jsonl`
  to actually be the artifact described in the original plan.
