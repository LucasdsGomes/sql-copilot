from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import Field


class RecordingFake(FakeListChatModel):
    """Fake LLM that replays canned responses and records every prompt it receives."""

    prompts: list = Field(default_factory=list)

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append("\n".join(str(m.content) for m in messages))
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)


class ExplodingFake(FakeListChatModel):
    """Fake LLM that fails the way a broken upstream provider would."""

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("upstream exploded: secret-internal-detail")
