"""A single OpenAI-compatible Chat Completions client.

All LLM-backed stages (Discovery, DOM Mapping, Implementation, Evaluation) go
through this one client. The Test Runner does not touch it.

Three modes keep the project both real and reproducible:

* ``live``   — POST to the configured OpenAI-compatible endpoint.
* ``replay`` — return responses recorded in a cassette JSON file, keyed by a
  per-call ``tag``. Lets the bundled example run with no model available.
* ``record`` — call ``live`` and append the response to the cassette.

The cassette is keyed by stage tag (not by a hash of the prompt) so it stays
robust to prompt wording changes.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from ..config import LLMConfig
from ..core.errors import DataError, LLMError


def parse_json_loose(text: str, *, context: str = "LLM output") -> Any:
    """Parse JSON from a model response, tolerating ```json fences and prose."""
    if text is None:
        raise DataError(f"{context}: empty response, expected JSON.")
    stripped = text.strip()
    # Strip a leading/trailing markdown code fence if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise DataError(f"{context}: could not parse JSON from response.")


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self._cassette: Optional[Dict[str, str]] = None
        if config.mode in ("replay", "record"):
            self._cassette = self._load_cassette()

    # -- cassette helpers -----------------------------------------------------

    def _load_cassette(self) -> Dict[str, str]:
        path = self.config.cassette
        if not path:
            raise LLMError(
                f"LLM mode '{self.config.mode}' requires a cassette file "
                "(--cassette / LLM_CASSETTE)."
            )
        if self.config.mode == "record" and not os.path.exists(path):
            return {}
        if not os.path.exists(path):
            raise LLMError(f"cassette file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise LLMError(f"could not read cassette '{path}': {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError(f"cassette '{path}' must be a JSON object of tag->text.")
        return data

    def _save_cassette(self) -> None:
        if self._cassette is None or not self.config.cassette:
            return
        with open(self.config.cassette, "w", encoding="utf-8") as fh:
            json.dump(self._cassette, fh, ensure_ascii=False, indent=2)

    # -- public API -----------------------------------------------------------

    def chat(self, system: str, user: str, *, tag: str) -> str:
        """Return the assistant message content for a single-turn request."""
        if self.config.mode == "replay":
            return self._replay(tag)
        content = self._live(system, user)
        if self.config.mode == "record":
            assert self._cassette is not None
            self._cassette[tag] = content
            self._save_cassette()
        return content

    def _replay(self, tag: str) -> str:
        assert self._cassette is not None
        if tag not in self._cassette:
            raise LLMError(
                f"cassette has no recorded response for stage '{tag}'. "
                f"Available: {', '.join(sorted(self._cassette)) or '(none)'}."
            )
        return self._cassette[tag]

    def _live(self, system: str, user: str) -> str:
        # Imported lazily so replay mode works even without `requests`.
        try:
            import requests
        except ImportError as exc:  # pragma: no cover
            raise LLMError("the 'requests' package is required for live mode.") from exc

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature,
        }
        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.config.timeout
            )
        except requests.exceptions.RequestException as exc:
            raise LLMError(
                f"could not reach LLM endpoint at {url}: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise LLMError(
                f"LLM endpoint returned HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"unexpected response shape from LLM endpoint: {exc}"
            ) from exc
