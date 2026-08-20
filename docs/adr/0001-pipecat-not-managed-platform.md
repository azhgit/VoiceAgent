# Pipecat as pipeline skeleton, not a managed agent platform

We're building the audio/telephony pipeline on Pipecat (Twilio Media
Streams → STT → LLM → TTS) instead of a fully managed voice-agent platform
like ElevenLabs Agents. The target role explicitly evaluates hands-on
ownership of a real-time voice pipeline — VAD/turn-taking tuning, latency
instrumentation, streaming wiring — and a managed platform would only
demonstrate "I can assemble someone else's product," not "I can maintain
this pipeline myself." Switching frameworks mid-build would also cost real
time this POC's 4–5 day budget doesn't have, so this choice is being locked
in now rather than revisited later.
