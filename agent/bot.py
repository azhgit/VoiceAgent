import os

import httpx
from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

from latency_observer import LatencyLogObserver
from silence_timeout import SilenceTimeoutProcessor

load_dotenv(override=True)

CRM_BASE_URL = os.getenv("CRM_BASE_URL", "http://localhost:8000")


def _vad_params_from_env() -> VADParams:
    # Untuned - Silero's own defaults (confidence=0.7, start_secs=0.2,
    # stop_secs=0.2) were picked for generic mic audio, not 8kHz phone
    # audio, but tuning them for real needs live call testing we can't do
    # here. Exposed as env vars so that testing can iterate without a code
    # change; unset vars fall back to VADParams' own defaults.
    overrides = {}
    for field, env_var in (
        ("confidence", "VAD_CONFIDENCE"),
        ("start_secs", "VAD_START_SECS"),
        ("stop_secs", "VAD_STOP_SECS"),
    ):
        value = os.getenv(env_var)
        if value:
            overrides[field] = float(value)
    return VADParams(**overrides)

# Day 1: real dispatch prompt with fixed urgency/specialty classification
# rules (see doc/voice-agent-poc-plan.md) - the caller never gets asked to
# self-classify, the agent decides from what they describe.
SYSTEM_INSTRUCTION = (
    "You are the after-hours dispatch line for a plumbing and HVAC company. "
    "Keep every reply to one or two short sentences - this is a phone call, "
    "not a chat.\n\n"
    "For every caller:\n"
    "1. Ask what's wrong if they haven't said, then classify BOTH the "
    "specialty and the urgency from their description. Use these fixed "
    "rules, don't improvise:\n"
    "   - specialty: 'plumbing' for water/pipe/drain/water-heater issues "
    "(including no hot water), 'hvac' for heating/cooling/air issues.\n"
    "   - urgency 'urgent': active water damage, no heat with near-freezing "
    "outdoor temps, a gas smell, or sewage backup.\n"
    "   - urgency 'non_urgent': a dripping faucet, no hot water, an unusual "
    "noise, or routine maintenance.\n"
    "2. Call check_availability with that specialty and urgency. Read the "
    "caller exactly the slots it returns as concrete options (e.g. "
    "'Tuesday at 2pm with Mike, or Wednesday at 10am with Dana') - never "
    "invent a time yourself. If it returns no slots, apologize and tell "
    "them someone will call back to schedule.\n"
    "3. Once the caller picks one, get their name and phone number, call "
    "book_appointment with that exact slot, and read back the confirmed "
    "time and technician name to close the call.\n"
)
KICKOFF_MESSAGE = (
    "The caller just connected. Greet them in one short sentence as the "
    "after-hours plumbing/HVAC dispatch line, then ask what's going on."
)


def build_tool_schemas() -> list[FunctionSchema]:
    """Schema-only tool definitions (no handlers attached here - those are
    wired separately via llm.register_function in run_bot). Factored out to
    a module-level function so eval_dispatch_classification.py can send the
    LLM the exact same tool definitions the live pipeline uses.
    """
    return [
        FunctionSchema(
            name="check_availability",
            description=(
                "Look up available appointment slots for a technician specialty "
                "and urgency. Returns a short list of concrete slots to read back "
                "to the caller verbatim."
            ),
            properties={
                "specialty": {
                    "type": "string",
                    "enum": ["plumbing", "hvac"],
                    "description": "Which trade the issue falls under.",
                },
                "urgency": {
                    "type": "string",
                    "enum": ["urgent", "non_urgent"],
                    "description": "Urgency classified per the fixed dispatch rules.",
                },
            },
            required=["specialty", "urgency"],
        ),
        FunctionSchema(
            name="book_appointment",
            description=(
                "Book one of the slots previously returned by check_availability "
                "for the caller."
            ),
            properties={
                "technician_id": {
                    "type": "integer",
                    "description": "technician_id from the chosen check_availability slot.",
                },
                "time_slot": {
                    "type": "string",
                    "description": (
                        "ISO 8601 timestamp of the chosen slot, exactly as returned "
                        "by check_availability."
                    ),
                },
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
                "urgency": {
                    "type": "string",
                    "enum": ["urgent", "non_urgent"],
                },
            },
            required=["technician_id", "time_slot", "customer_name", "customer_phone", "urgency"],
        ),
    ]


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    llm = AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        settings=AnthropicLLMService.Settings(
            model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5"),
            system_instruction=SYSTEM_INSTRUCTION,
        ),
    )
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        settings=DeepgramSTTService.Settings(model="nova-3-general"),
    )
    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        settings=ElevenLabsTTSService.Settings(
            voice=os.getenv("ELEVENLABS_VOICE_ID"),
            model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        ),
    )

    crm_client = httpx.AsyncClient(base_url=CRM_BASE_URL, timeout=5.0)

    async def check_availability(params: FunctionCallParams):
        specialty = params.arguments["specialty"]
        urgency = params.arguments["urgency"]
        try:
            response = await crm_client.get(
                "/availability", params={"specialty": specialty, "urgency": urgency}
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"CRM availability lookup failed: {e}")
            await params.result_callback({"error": "crm_unavailable"})
            return
        await params.result_callback({"slots": response.json()})

    async def book_appointment(params: FunctionCallParams):
        args = params.arguments
        try:
            response = await crm_client.post(
                "/appointments",
                json={
                    "technician_id": args["technician_id"],
                    "time_slot": args["time_slot"],
                    "customer_name": args["customer_name"],
                    "customer_phone": args["customer_phone"],
                    "urgency": args["urgency"],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            # Includes 409 slot-conflict responses from the CRM - surfaced to
            # the LLM as a generic failure rather than a distinct "recheck
            # availability" signal. Fine for now; revisit if this shows up in
            # real calls.
            logger.error(f"CRM booking failed: {e}")
            await params.result_callback({"error": "booking_failed"})
            return
        await params.result_callback({"appointment": response.json()})

    llm.register_function("check_availability", check_availability)
    llm.register_function("book_appointment", book_appointment)

    tools = build_tool_schemas()

    # Seeded as a "user" turn, not "system": Anthropic's context requires the
    # message list to start with a real conversational role, and this message
    # is a one-time kickoff instruction, not the persistent system prompt
    # (that's SYSTEM_INSTRUCTION above, passed via Settings).
    context = LLMContext([{"role": "user", "content": KICKOFF_MESSAGE}], tools=tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=_vad_params_from_env())
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,  # emits UserStartedSpeakingFrame - must come before the watcher below
            SilenceTimeoutProcessor(),
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,  # Twilio Media Streams: 8kHz mulaw
            audio_out_sample_rate=8000,
            enable_metrics=True,  # feeds the TTFB/TTFA frames LatencyLogObserver reads
            enable_usage_metrics=True,
        ),
        observers=[LatencyLogObserver()],
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Twilio stream connected - kicking off greeting")
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await worker.cancel()
        await crm_client.aclose()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint, force_gc=True)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    transport_params = {
        "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
