"""Model interface. The agent only needs one thing from a model: given a prompt,
return a JSON object. Gemini is the real backend; ScriptedLLM replays fixed
answers so the whole pipeline can be tested offline."""
from __future__ import annotations

import json
import os
import re
from typing import Callable, Protocol


class LLM(Protocol):
    name: str

    def json(self, prompt: str) -> dict: ...


def parse_json(text: str) -> dict:
    """Parse a JSON object even if the model wrapped it in a code fence or added text around it."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"Model did not return JSON: {text[:200]}")
        return json.loads(text[start:end + 1])


class GeminiLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None, temperature: float = 0.2):
        from google import genai

        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)")
        self.client = genai.Client(api_key=key)
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.temperature = temperature
        self.name = f"Gemini ({self.model})"

    def json(self, prompt: str) -> dict:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=self.temperature, response_mime_type="application/json"),
        )
        return parse_json(resp.text or "")


class ScriptedLLM:
    """Test double. `script` maps a step name (the first line of the prompt, e.g.
    'STEP: extract_requirements') to a dict, a list of dicts (used in order) or a function."""

    name = "Scripted model"

    def __init__(self, script: dict[str, dict | list | Callable[[str], dict]]):
        self.script = {k: (list(v) if isinstance(v, list) else v) for k, v in script.items()}
        self.prompts: list[str] = []

    def json(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        step = prompt.split("\n", 1)[0].removeprefix("STEP:").strip()
        answer = self.script[step]
        if isinstance(answer, list):
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer(prompt) if callable(answer) else answer
