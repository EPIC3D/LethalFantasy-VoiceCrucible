"""Director using any OpenAI-compatible chat API: local (Ollama, LM Studio) or cloud (with the user's key).

The key is read from an environment variable only – never from the config file, never logged, never sent
to workers. Each scene is one request; the answer must be a JSON object {key: direction}.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from voicecrucible.directors.base import Director, SceneLine, clean


class ApiDirectorError(RuntimeError):
    """The API answered with an error or with something that is not usable JSON."""


class ApiDirector(Director):
    """Chat-completions client with a director brief as system prompt."""

    def __init__(self, base_url: str, model: str, brief: str, api_key_env: str, timeout: float = 300):
        if not model:
            raise ApiDirectorError("[director] model is empty – set the model name of your API")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.brief = brief
        self._key = os.environ.get(api_key_env, "")
        self.timeout = timeout

    def direct(self, scene: str, lines: list[SceneLine]) -> dict[str, dict]:
        """Ask the model for the directions of one scene."""
        listing = "\n".join(
            f"{'' if ln.voiced else '[not voiced] '}{ln.key} | {ln.speaker} | expression: {ln.expression} | {ln.text}"
            for ln in lines)
        body = {"model": self.model, "temperature": 0.4, "messages": [
            {"role": "system", "content": self.brief},
            {"role": "user", "content": f"Scene: {scene}\n\n{listing}\n\nAnswer with the JSON object only."}]}
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                answer = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ApiDirectorError(f"API error {e.code}: {e.read()[:300].decode('utf-8', 'replace')}") from None
        content = answer["choices"][0]["message"]["content"]
        voiced = {ln.key for ln in lines if ln.voiced}
        return {k: v for k, v in clean(_first_json_object(content)).items() if k in voiced}


def _first_json_object(text: str) -> dict:
    """The JSON object in a model answer (tolerates ```json fences and text around it)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ApiDirectorError("the model did not answer with JSON")
    try:
        data = json.loads(m.group(0))
    except ValueError as e:
        raise ApiDirectorError(f"the model answered with broken JSON: {e}") from None
    if not isinstance(data, dict):
        raise ApiDirectorError("the model's JSON is not an object")
    return data
