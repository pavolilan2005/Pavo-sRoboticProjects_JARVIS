import asyncio

from prp.services.gemini_live import GeminiLiveService


class FakeConfig:
    def load(self, name, default=None):
        if name == "app.json":
            return {
                "assistant": {"wake_words": ["jarvis"], "followup_seconds": 30},
                "gemini": {"model": "gemini-3.1-flash-live-preview", "voice": "Charon"},
            }
        return default

    def secrets(self):
        return {}


class FakeAudio:
    def set_speaking(self, value):
        self.speaking = value


class FakeController:
    def __init__(self):
        self.config = FakeConfig()
        self.audio = FakeAudio()


class FakeCallbacks:
    def __init__(self):
        self.states = []
        self.logs = []

    def state(self, value):
        self.states.append(value)

    def log(self, value):
        self.logs.append(value)

    def transcript(self, who, text):
        pass


def test_missing_key_keeps_loop_alive():
    async def scenario():
        service = GeminiLiveService(FakeController(), FakeCallbacks())
        task = asyncio.create_task(service.run())
        await asyncio.sleep(0.05)
        assert service.running
        assert service.loop is asyncio.get_running_loop()
        # No session: audio is ignored safely instead of touching a closed loop.
        service.push_mic(b"\x00\x00" * 32)
        service.request_stop()
        await asyncio.wait_for(task, timeout=1.0)
        assert not service.running

    asyncio.run(scenario())
