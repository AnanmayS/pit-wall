"""Exercise the ask loop with a fake client: no network, no API key."""

from types import SimpleNamespace

import pitwall.ai.ask as ask_mod


class _Block(SimpleNamespace):
    pass


def _msg(stop, content):
    return SimpleNamespace(
        stop_reason=stop, content=content, usage=SimpleNamespace(input_tokens=10, output_tokens=5)
    )


class FakeClient:
    """First turn calls a tool; second turn answers with an invented number; third turn fixes it."""

    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        if self.calls == 1:
            return _msg("tool_use", [_Block(type="tool_use", id="t1", name="fake", input={"x": 1})])
        if self.calls == 2:
            return _msg("end_turn", [_Block(type="text", text="The delta was 0.99 s.")])
        return _msg("end_turn", [_Block(type="text", text="The delta was 0.12 s.")])


def test_rewrite_then_grounded(monkeypatch):
    monkeypatch.setattr(ask_mod, "execute", lambda name, inputs: ({"total_delta_ms": 123}, False))
    res = ask_mod.ask("q", client=FakeClient(), model="test-model")
    assert res.grounded and res.rewrites == 1 and res.turns == 3
    assert res.tool_calls[0].name == "fake"


def test_refuses_after_failed_rewrite(monkeypatch):
    class Stubborn(FakeClient):
        def create(self, **kw):
            self.calls += 1
            if self.calls == 1:
                return _msg("tool_use", [_Block(type="tool_use", id="t1", name="fake", input={})])
            return _msg("end_turn", [_Block(type="text", text="It was 0.99 s.")])

    monkeypatch.setattr(ask_mod, "execute", lambda name, inputs: ({"total_delta_ms": 123}, False))
    res = ask_mod.ask("q", client=Stubborn(), model="test-model")
    assert res.refused and not res.grounded and "0.99" in res.answer
