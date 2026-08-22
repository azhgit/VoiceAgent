import asyncio
import random

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    StartFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

FILLER_PHRASES = [
    "Let me check on that...",
    "One moment...",
    "Let me look into that for you...",
]


class ThinkingFillerProcessor(FrameProcessor):
    """If the bot hasn't started responding within delay_secs of the caller
    finishing their turn, speak one short filler phrase - masks the LLM's
    thinking time (and the extra round trip on tool-calling turns) instead
    of leaving dead air the caller might mistake for "not responding" and
    talk over.

    Fires at most once per turn: disarms on BotStartedSpeakingFrame (the
    real response is coming, no filler needed) and on
    UserStartedSpeakingFrame (the caller is talking again, don't talk over
    them). The only way to re-arm is the next UserStoppedSpeakingFrame, so
    firing and re-arming are the same _armed flag by construction - no
    separate "already fired this turn" state needed.
    """

    def __init__(
        self, *, delay_secs: float = 1.2, phrases: list[str] | None = None, **kwargs
    ):
        super().__init__(**kwargs)
        self._delay_secs = delay_secs
        self._phrases = phrases or list(FILLER_PHRASES)
        self._armed = False
        self._activity_event = asyncio.Event()
        self._watch_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._watch_task = self.create_task(self._watch())
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._armed = True
            self._activity_event.set()
        elif isinstance(frame, (BotStartedSpeakingFrame, UserStartedSpeakingFrame)):
            self._armed = False
            self._activity_event.set()

        await self.push_frame(frame, direction)

    async def cleanup(self):
        if self._watch_task:
            await self.cancel_task(self._watch_task)

    async def _watch(self):
        while True:
            while not self._armed:
                await self._activity_event.wait()
                self._activity_event.clear()
            try:
                await asyncio.wait_for(self._activity_event.wait(), timeout=self._delay_secs)
                self._activity_event.clear()
                # Disarmed before the delay elapsed (bot started for real, or
                # the caller started talking again) - loop back to the outer
                # wait, which will go idle since _armed is now False.
            except TimeoutError:
                if self._armed:
                    self._armed = False  # single-fire-per-turn reset
                    await self.push_frame(
                        TTSSpeakFrame(text=random.choice(self._phrases)),
                        FrameDirection.DOWNSTREAM,
                    )
