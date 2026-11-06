"""Run one Decisions API request per text test."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .definitions import PreparedTest


ENDPOINT = "https://api.openai.com/v1/decisions"


class DecisionError(Exception):
    """A request or response that cannot produce a test result."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DecisionError("The Decisions API request was redirected; the request was stopped.")


class DecisionsClient:
    """Send requests once, without automatic retries or HTTP redirects."""

    def __init__(self, api_key: str, timeout: float = 60.0):
        if not isinstance(api_key, str) or not api_key.strip():
            raise DecisionError("OPENAI_API_KEY is missing.")
        api_key = api_key.strip()
        if any(character.isspace() for character in api_key):
            raise DecisionError("OPENAI_API_KEY contains whitespace.")
        self._api_key = api_key
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_NoRedirect())

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise DecisionError("The test request could not be encoded as JSON.") from None

        request = urllib.request.Request(
            ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise DecisionError(f"The Decisions API returned HTTP {code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise DecisionError("The Decisions API request failed or timed out.") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise DecisionError("The Decisions API returned invalid JSON.") from None
        if not isinstance(result, dict):
            raise DecisionError("The Decisions API returned an invalid response object.")
        return result


@dataclass(frozen=True)
class TestResult:
    test: PreparedTest
    value: float | None
    status: str
    error: str | None = None


class TestRunner:
    """Evaluate tests once and interpret their Decisions API answers."""

    def __init__(self, client: DecisionsClient):
        self.client = client

    def run(self, test: PreparedTest) -> TestResult:
        """Keep a request or response error separate from a failed criterion."""
        try:
            response = self.client.create(test.payload)
            return self._decode_result(test, response)
        except DecisionError as error:
            return TestResult(test=test, value=None, status="ERROR", error=str(error))

    def _decode_result(self, test: PreparedTest, response: dict[str, Any]) -> TestResult:
        if not isinstance(response, dict):
            raise DecisionError("The Decisions API returned an invalid response object.")
        answers = response.get("answers")
        if not isinstance(answers, list) or len(answers) != 1:
            raise DecisionError("The Decisions API must return exactly one answer for this test.")
        answer = answers[0]
        if not isinstance(answer, dict) or answer.get("name") != test.name:
            raise DecisionError("The Decisions API returned an answer for a different test.")
        if answer.get("type") == "refusal":
            raise DecisionError("The model refused to evaluate this test.")
        if answer.get("type") != test.kind:
            raise DecisionError("The Decisions API returned an unexpected answer type.")

        if test.kind == "predicate":
            value = self._number(answer.get("probability"), "probability", 0, 1)
        elif test.kind == "score":
            value = self._number(answer.get("score"), "score", 0, 4) + 1
        else:
            raise DecisionError("This test has an unsupported question type.")
        status = "PASS" if value >= test.minimum else "FAIL"
        return TestResult(test=test, value=value, status=status)

    @staticmethod
    def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
        # The range check also rejects NaN and infinities, and happens before
        # converting potentially large JSON integers to floats.
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not minimum <= value <= maximum
        ):
            raise DecisionError(f"The Decisions API returned an invalid {label}.")
        return float(value)
