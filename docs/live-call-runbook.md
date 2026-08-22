# Live call runbook

Steps to place one real phone call through the full pipeline (Twilio →
Pipecat → Deepgram → Claude → ElevenLabs → mock CRM) and capture the
artifacts the plan still needs: real `agent/latency_log.jsonl` data, a
demo recording, and confidence the whole thing actually works end to end.

No code changes are needed for this — `agent/bot.py` already uses
Pipecat's built-in dev runner (`pipecat.runner.run.main()`), which handles
the Twilio webhook and WebSocket wiring automatically once you pass it the
right flags. This is purely an infra/config checklist.

## Prerequisites

- Twilio account with a phone number (`TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` in `.env` — already there per
  `.env.example`)
- [ngrok](https://ngrok.com/) installed and authenticated
  (`ngrok config add-authtoken <token>`, from your ngrok dashboard)
- `.env` filled in with real `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`,
  `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- `crm/` and `agent/` venvs already set up (`pip install -r
  requirements.txt` in each, per the README)

## 1. Start the CRM

```bash
cd crm
.venv/bin/python seed.py          # reset to clean demo data
.venv/bin/uvicorn main:app --port 8000
```

Leave this running. If port 8000 is already taken by another project on
your machine (`lsof -nP -iTCP:8000 -sTCP:LISTEN` to check), use `--port
8001` instead — just make sure `CRM_BASE_URL` in `.env` matches whatever
port you actually use here.

## 2. Start ngrok

In a new terminal:

```bash
ngrok http 7860
```

7860 is Pipecat's default local port (matches what `agent/bot.py` will
listen on in step 4 — override both together with `--port` if you need a
different one). Copy the `https://xxxx.ngrok-free.app` forwarding URL ngrok
prints — you'll need the hostname (without `https://`) in steps 3 and 4.

**Free ngrok plan**: this hostname is random and changes every time you
restart ngrok. If that happens, redo step 3 with the new hostname before
calling again.

## 3. Point the Twilio number at ngrok

In the [Twilio Console](https://console.twilio.com/):

1. Phone Numbers → Manage → Active Numbers → click your number
2. Under **Voice Configuration**, set "A call comes in" to:
   - **Webhook**, HTTP method **POST**
   - URL: `https://xxxx.ngrok-free.app/` (the ngrok hostname from step 2,
     root path — this is the endpoint that returns the TwiML pointing
     Twilio's Media Stream at this same tunnel's `/ws`)
3. Save

## 4. Start the agent

```bash
cd agent
.venv/bin/python bot.py -t twilio -x xxxx.ngrok-free.app
```

`-x`/`--proxy` takes just the hostname (no `https://` — the runner adds
`wss://` itself when building the TwiML). This starts a local server on
`localhost:7860` that serves both the Twilio webhook (`POST /`) and the
Media Stream WebSocket (`/ws`).

## 5. Call it

Dial the Twilio number from a real phone. Try both branches from
`CONTEXT.md` so the demo recording (see below) actually exercises the
interesting paths, not just the happy path:

- **Non-urgent, successful booking**: "My kitchen faucet has been
  dripping for a few days" → pick one of the offered slots, give a name
  and phone number, confirm the booking read-back.
- **Urgent**: "There's water pouring out from under my sink and flooding
  the floor!" → confirm it offers the on-call technician's slots, or
  triggers the *Handoff simulation* if none are available.
- **Barge-in**: start talking while the bot is mid-sentence, confirm it
  stops immediately instead of finishing its sentence.
- **Silence**: go quiet mid-call for ~8s, confirm the "Are you still
  there?" check-in fires; stay silent through another ~8s and confirm it
  says goodbye and hangs up.
- **Unclear speech**: say something nonsensical or off-topic twice in a
  row, confirm it asks you to repeat once, then transfers on the second
  miss.

## 6. After the call

```bash
cd agent
.venv/bin/python visualize_latency.py
```

This reads the real `agent/latency_log.jsonl` written during the call and
writes `agent/latency_chart.png` — the actual artifact the plan wants,
not the synthetic-data version that was only there to prove the script
works.

## Troubleshooting

- **Call connects but there's no audio / garbled audio**: check the CRM
  and agent logs for errors first. Audio format mismatches would show up
  here — `PipelineParams` in `agent/bot.py` is already set to 8kHz to
  match Twilio's mulaw stream, so this is more likely an API key or
  network issue than a format one.
- **Twilio webhook returns an error / call fails immediately**: check
  that ngrok is still running and the Console webhook URL matches its
  *current* hostname (see the free-plan note in step 2).
- **Agent can't reach the CRM**: confirm `crm`'s uvicorn is still running
  on the port `CRM_BASE_URL` in `.env` points to.
- **Bot never says anything**: check `ANTHROPIC_API_KEY` /
  `DEEPGRAM_API_KEY` / `ELEVENLABS_API_KEY` are all real, non-empty
  values in `.env` — `load_dotenv(override=True)` in `bot.py` will happily
  start with a blank key and just fail silently downstream.
