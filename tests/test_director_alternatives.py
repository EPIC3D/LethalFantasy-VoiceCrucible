"""Random alternatives of a scene are not shown to the director as one conversation."""

from voicecrucible.directors import api
from voicecrucible.directors.base import SceneLine


def test_only_the_asked_alternatives_are_context(monkeypatch):
    seen = {}

    def fake_post(self, url, body):
        seen["prompt"] = body["messages"][1]["content"]
        return {"choices": [{"message": {"content": '{"K_1": {"intent": "x"}}'}}]}

    monkeypatch.setattr(api, "_ollama_root", lambda url: "")
    monkeypatch.setattr(api.ApiDirector, "_post", fake_post)
    d = api.ApiDirector("http://x/v1", "m", "brief", "NO_KEY")
    lines = [SceneLine("K_1", "A", "Roof one", "Smile", True, 0), SceneLine("K_2", "A", "Roof two", "Smile", True, 1)]
    d._ask("S", lines, ["K_1"])
    assert "Roof one" in seen["prompt"] and "Roof two" not in seen["prompt"]
    assert "[alternative 1]" in seen["prompt"]
