"""Local models through Ollama (free, private, runs on this PC).

Uses /api/chat with `format` = the JSON schema of the expected answer, so the
model can only produce schema-shaped JSON; we still validate with Pydantic and
retry once with the validation error if it slips. `think: false` skips the
reasoning phase of hybrid models (much faster for this kind of task).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from clipforge.ai.base import AIError, T, Usage


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        model: str,
        url: str = "http://127.0.0.1:11434",
        *,
        transport: httpx.BaseTransport | None = None,
        temperature: float = 0.2,
        num_ctx: int = 16384,
    ) -> None:
        self.model = model
        self.url = url.rstrip("/")
        self.transport = transport
        self.temperature = temperature
        self.num_ctx = num_ctx

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=timeout)

    def health(self) -> tuple[bool, str]:
        try:
            with self._client(5) as c:
                r = c.get(f"{self.url}/api/tags")
                r.raise_for_status()
                names = [m.get("name", "") for m in r.json().get("models", [])]
        except httpx.HTTPError as e:
            return (
                False,
                f"Ollama is not reachable at {self.url} ({e.__class__.__name__}). Start Ollama.",
            )
        base = self.model.split(":")[0]
        if self.model in names or any(
            n.split(":")[0] == base and ":" not in self.model for n in names
        ):
            return True, f"Ollama ready, model {self.model}"
        return False, f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"

    def list_models(self) -> list[str]:
        with self._client(5) as c:
            r = c.get(f"{self.url}/api/tags")
            r.raise_for_status()
            return sorted(m.get("name", "") for m in r.json().get("models", []))

    def _chat(
        self, messages: list[dict[str, str]], schema: dict[str, Any], timeout: float
    ) -> tuple[str, Usage]:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        t0 = time.monotonic()
        try:
            with self._client(timeout) as c:
                r = c.post(f"{self.url}/api/chat", json=body)
        except httpx.TimeoutException:
            raise AIError(f"Ollama did not answer within {timeout:.0f}s") from None
        except httpx.HTTPError as e:
            raise AIError(f"Ollama is not reachable at {self.url}: {e}") from None
        if r.status_code != 200:
            detail = r.text[:300]
            if "not found" in detail.lower():
                raise AIError(
                    f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"
                )
            raise AIError(f"Ollama error {r.status_code}: {detail}")
        d = r.json()
        usage = Usage(
            self.name,
            self.model,
            input_tokens=int(d.get("prompt_eval_count") or 0),
            output_tokens=int(d.get("eval_count") or 0),
            seconds=time.monotonic() - t0,
            calls=1,
        )
        return str((d.get("message") or {}).get("content") or ""), usage

    def complete_json(
        self, system: str, user: str, schema: type[T], *, timeout: float
    ) -> tuple[T, Usage]:
        js = schema.model_json_schema()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        total = Usage(self.name, self.model)
        last_error = ""
        for attempt in range(2):
            text, usage = self._chat(messages, js, timeout)
            total.add(usage)
            try:
                return schema.model_validate(json.loads(text)), total
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)[:500]
                if attempt == 0:  # one repair round with the exact error
                    messages += [
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": "That JSON did not match the schema:\n"
                            f"{last_error}\nReply again with only corrected JSON.",
                        },
                    ]
        raise AIError(f"{self.model} returned invalid JSON twice: {last_error}")
