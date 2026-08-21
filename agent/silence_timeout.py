import asyncio

from pipecat.frames.frames import EndFrame, Frame, StartFrame, TTSSpeakFrame, UserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

CHECK_IN_MESSAGE = "Are you still there?"
GOODBYE_MESSAGE = (
    "I haven't heard from you in a while, so I'll go ahead and end the call "
    "now. Feel free to call back anytime."
)


class SilenceTimeoutProcessor(FrameProcessor):
    """~8s with no UserStartedSpeakingFrame -> bot checks in once. Another
    ~8s of silence after that -> bot says goodbye and ends the call.

    Only resets on the caller actually speaking (UserStartedSpeakingFrame),
    not on the bot's own turns - so normal LLM/TTS latency between turns
    never counts as "silence" here, only genuine caller silence does.
    """

    def __init__(self, *, timeout_secs: float = 8.0, **kwargs):
        super().__init__(**kwargs)
        self._timeout_secs = timeout_secs
        self._triggers = 0
        self._activity_event = asyncio.Event()
        self._timeout_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._timeout_task = self.create_task(self._watch())
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._triggers = 0
            self._activity_event.set()

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
