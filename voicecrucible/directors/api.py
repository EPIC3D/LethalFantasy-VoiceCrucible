"""Director using any OpenAI-compatible chat API: local (Ollama, LM Studio) or cloud (with the user's key).

The key is read from an environment variable only – never from the config file, never logged, never sent
to workers. Each scene is one request; the answer must be a JSON object {key: direction}.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from voicecrucible.directors.base import Director, SceneLine, clean


CHUNK = 8  # voiced lines per request
WHOLE_SCENE_MAX = 40  # longer scenes: only the lines around the requested ones are sent
CONTEXT_AROUND = 10


class ApiDirectorError(RuntimeError):
    """The API answered with an error or with something that is not usable JSON."""


class ApiDirector(Director):
    """Chat-completions client with a director brief as system prompt."""

    def __init__(self, base_url: str, model: str, brief: str, api_key_env: str, timeout: float = 300,
                 context_length: int = 0):
        if not model:
            raise ApiDirectorError("[director] model is empty – set the model name of your API")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.brief = brief
        self._key = os.environ.get(api_key_env, "")
        self.timeout = timeout
        self.context_length = context_length
        # Ollama: use its own API, which can set the context size (VRAM), turn off "thinking" and unload the model.
        self.ollama = _ollama_root(base_url)

    def direct(self, scene: str, lines: list[SceneLine]) -> dict[str, dict]:
        """Directions for one scene. Long scenes are asked for in parts (small local models skip lines or
        loop on long answers); the whole scene is always shown as context. Missing keys are asked once more."""
        voiced = [ln.key for ln in lines if ln.voiced]
        out: dict[str, dict] = {}
        for attempt in range(2):
            todo = [k for k in voiced if k not in out]
            for i in range(0, len(todo), CHUNK):
                part = todo[i:i + CHUNK]
                try:
                    out.update({k: v for k, v in self._ask(scene, lines, part).items() if k in part})
                except ApiDirectorError:
                    if attempt:
                        raise
        if not out:
            raise ApiDirectorError("the model gave no usable directions")
        return out

    def _ask(self, scene: str, lines: list[SceneLine], keys: list[str]) -> dict[str, dict]:
        """One request: directions for `keys`, with the scene as context. Very long scenes (100+ random alternatives
        such as growth reactions) do not fit a local model's context: then only the lines around `keys` are shown."""
        alts = {ln.alt for ln in lines if ln.key in keys}
        several = len({ln.alt for ln in lines}) > 1 and -1 not in alts
        if several:  # random alternatives are separate moments: only the asked ones are context, not their neighbours
            lines = [ln for ln in lines if ln.alt in alts]
        if len(lines) > WHOLE_SCENE_MAX:
            idx = [i for i, ln in enumerate(lines) if ln.key in keys]
            lo, hi = max(0, min(idx) - CONTEXT_AROUND), min(len(lines), max(idx) + CONTEXT_AROUND + 1)
            lines = lines[lo:hi]
        listing = "\n".join(
            f"{f'[alternative {ln.alt + 1}] ' if several else ''}{'' if ln.voiced else '[not voiced] '}{ln.key} | "
            f"{ln.speaker} | expression: {ln.expression} | {ln.text}" for ln in lines)
        ask = ", ".join(keys)
        note = ("\nLines marked [alternative N] are separate random alternatives of the same moment – the game plays "
                "only one of them. Only lines with the same N are one continuous exchange; do not read the other "
                "alternatives as what was said before or after.\n" if several else "")
        messages = [{"role": "system", "content": self.brief},
                    {"role": "user", "content": f"Scene: {scene}\n{note}\n{listing}\n\nWrite directions ONLY for these "
                     f"{len(keys)} keys: {ask}\nAnswer with the JSON object only."}]
        if self.ollama:
            options: dict = {"temperature": 0.4, "repeat_penalty": 1.1}
            if self.context_length:
                options["num_ctx"] = self.context_length
            body = {"model": self.model, "messages": messages, "stream": False, "think": False,
                    "format": "json", "options": options}
            content = self._post(self.ollama + "/api/chat", body)["message"]["content"]
        else:
            body = {"model": self.model, "temperature": 0.4, "messages": messages}
            content = self._post(self.url, body)["choices"][0]["message"]["content"]
        return clean(_first_json_object(content))

    def unload(self) -> None:
        """Free the GPU memory right away (Ollama keeps a model loaded for minutes) so a worker can use it."""
        if self.ollama:
            try:
                self._post(self.ollama + "/api/generate", {"model": self.model, "keep_alive": 0})
            except (ApiDirectorError, OSError):
                pass

    def _post(self, url: str, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), headers)
        for wait in (3, 10, None):  # transient errors (a dropped local connection, a busy server) are retried
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                text = e.read()[:300].decode("utf-8", "replace")
                if wait is None or not (e.code in (429, 502, 503) or (e.code == 500 and "tcp" in text)):
                    raise ApiDirectorError(f"API error {e.code}: {text}") from None
            except (ConnectionError, urllib.error.URLError):
                if wait is None:
                    raise
            time.sleep(wait)
        raise ApiDirectorError("unreachable")


def _ollama_root(base_url: str) -> str:
    """The server root when base_url points at Ollama (it answers /api/version), else ''."""
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(root + "/api/version", timeout=3) as r:
            return root if "version" in json.loads(r.read()) else ""
    except (OSError, ValueError):
        return ""


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
