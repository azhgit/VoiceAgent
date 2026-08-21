import asyncio

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

CHECK_IN_MESSAGE = "Are you still there?"
GOODBYE_MESSAGE = (
    "I haven't heard from you in a while, so I'll go ahead and end the call "
    "now. Feel free to call back anytime."
)


class SilenceTimeoutProcessor(FrameProcessor):
    """~8s with no caller response after the bot finishes speaking -> bot
    checks in once. Another ~8s of silence after that -> bot says goodbye
    and ends the call.

    The waiting window only starts once the bot has actually stopped
    speaking (BotStoppedSpeakingFrame) and is paused while the bot is
    speaking (BotStartedSpeakingFrame) - otherwise a slow LLM/TTS turn
    eats into the caller's silence budget, and the check-in can fire right
    as the bot finishes talking instead of after real caller silence.
    The escalation counter (_triggers) only resets on the caller actually
    speaking (UserStartedSpeakingFrame), not on BotStoppedSpeakingFrame -
    otherwise the check-in's own TTS turn would reset it and stage 2
    (goodbye) would never be reachable.
    """

    def __init__(self, *, timeout_secs: float = 8.0, **kwargs):
        super().__init__(**kwargs)
        self._timeout_secs = timeout_secs
        self._triggers = 0
        self._bot_speaking = False
        self._activity_event = asyncio.Event()
        self._timeout_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._timeout_task = self.create_task(self._watch())
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._triggers = 0
            self._activity_event.set()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._activity_event.set()  # don't let a timeout land mid-speech
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._activity_event.set()  # caller's silence window starts now

        await self.push_frame(frame, direction)

    async def cleanup(self):
        if self._timeout_task:
            await self.cancel_task(self._timeout_task)

    async def _watch(self):
        while True:
            try:
                await asyncio.wait_for(self._activity_event.wait(), timeout=self._timeout_secs)
                self._activity_event.clear()
            except TimeoutError:
                if self._bot_speaking:
                    # A long bot turn is still in progress - not caller
                    # silence, just keep waiting for it to finish.
                    continue
                self._triggers += 1
                if self._triggers == 1:
                    await self.push_frame(
                        TTSSpeakFrame(text=CHECK_IN_MESSAGE), FrameDirection.DOWNSTREAM
                    )
                else:
                    await self.push_frame(
                        TTSSpeakFrame(text=GOODBYE_MESSAGE), FrameDirection.DOWNSTREAM
                    )
                    await self.push_frame(
                        EndFrame(reason="silence timeout"), FrameDirection.DOWNSTREAM
                    )
                    return
