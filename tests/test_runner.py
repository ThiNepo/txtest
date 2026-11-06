"""Offline checks for the Decisions transport and pass/fail interpretation."""

import io
import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from txtest.definitions import PreparedTest
from txtest.runner import (
    ENDPOINT,
    DecisionError,
    DecisionsClient,
    TestRunner,
    _NoRedirect,
)


FAKE_KEY = "fake-unit-test-key"


def prepared(kind="predicate", minimum=None):
    return PreparedTest(
        name="reasoning",
        description="Explains what, how, and why at every step.",
        kind=kind,
        minimum=(0.5 if kind == "predicate" else 4.0) if minimum is None else minimum,
        payload={
            "model": "gpt-6-luna",
            "input": "A text to evaluate.",
            "questions": [{"type": kind, "name": "reasoning", "instructions": "Evaluate it."}],
        },
    )


def answer(kind="predicate", value=0.75, **overrides):
    field = "probability" if kind == "predicate" else "score"
    return {"answers": [{"type": kind, "name": "reasoning", field: value, **overrides}]}


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.runner = TestRunner(self.client)

    def test_predicate_threshold_is_inclusive_and_not_rounded(self):
        test = prepared(minimum=0.9)
        for value, expected in ((0, "FAIL"), (0.899999, "FAIL"), (0.9, "PASS"), (1, "PASS")):
            with self.subTest(value=value):
                self.client.create.return_value = answer(value=value)
                result = self.runner.run(test)
                self.assertEqual(result.status, expected)
                self.assertEqual(result.value, value)
                self.assertEqual(result.test.description, test.description)

    def test_score_maps_five_levels_to_one_through_five_without_rounding(self):
        test = prepared("score")
        for raw, expected, status in ((0, 1, "FAIL"), (2.99999, 3.99999, "FAIL"), (3, 4, "PASS"), (4, 5, "PASS")):
            with self.subTest(raw=raw):
                self.client.create.return_value = answer("score", raw)
                result = self.runner.run(test)
                self.assertAlmostEqual(result.value, expected)
                self.assertEqual(result.status, status)

    def test_invalid_numbers_cannot_become_passes_or_failures(self):
        for kind in ("predicate", "score"):
            for value in (None, True, False, "0.9", [], {}, float("nan"), float("inf"), -0.01, 10, 10**400):
                with self.subTest(kind=kind, value=repr(value)):
                    self.client.create.return_value = answer(kind, value)
                    result = self.runner.run(prepared(kind))
                    self.assertEqual(result.status, "ERROR")
                    self.assertIsNone(result.value)
                    self.assertTrue(result.error)

    def test_refusal_wrong_names_and_malformed_responses_are_errors(self):
        responses = (
            None, [], {}, {"answers": None}, {"answers": {}}, {"answers": []},
            {"answers": [None]}, {"answers": [{"name": "reasoning"}]},
            {"answers": answer()["answers"] * 2},
            answer(name="some_other_test"), answer(type="choice"),
            {"answers": [{"type": "refusal", "name": "reasoning"}]},
        )
        for response in responses:
            with self.subTest(response=response):
                self.client.create.return_value = response
                result = self.runner.run(prepared())
                self.assertEqual(result.status, "ERROR")
                self.assertIsNone(result.value)
                self.assertTrue(result.error)

    def test_runner_calls_once_and_keeps_errors_separate(self):
        test = prepared()
        for response, status in ((answer(value=0.8), "PASS"), (answer(value=0.1), "FAIL"), ({"answers": []}, "ERROR")):
            client = Mock()
            client.create.return_value = response
            with self.subTest(status=status):
                result = TestRunner(client).run(test)
                self.assertEqual(result.status, status)
                self.assertEqual(result.test, test)
                client.create.assert_called_once_with(test.payload)
                if status == "ERROR":
                    self.assertIsNone(result.value)
                    self.assertTrue(result.error)
        client = Mock()
        client.create.side_effect = DecisionError("Request failed.")
        self.assertEqual(TestRunner(client).run(test).error, "Request failed.")
        client.create.assert_called_once()


class TransportTests(unittest.TestCase):
    def test_request_uses_fixed_https_endpoint_and_key_only_in_header(self):
        response = answer()
        with patch.object(urllib.request.OpenerDirector, "open", return_value=io.BytesIO(json.dumps(response).encode())) as network:
            client = DecisionsClient(FAKE_KEY, timeout=2.5)
            self.assertEqual(client.create(prepared().payload), response)
            network.assert_called_once()
            request = network.call_args.args[0]
            self.assertEqual(request.full_url, ENDPOINT)
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + FAKE_KEY)
            self.assertEqual(json.loads(request.data), prepared().payload)
            self.assertNotIn(FAKE_KEY.encode(), request.data)
            self.assertEqual(network.call_args.kwargs["timeout"], 2.5)

    def test_network_http_and_json_errors_are_sanitized_and_never_retried(self):
        errors = (
            urllib.error.HTTPError(ENDPOINT, 401, FAKE_KEY, {}, io.BytesIO(FAKE_KEY.encode())),
            urllib.error.URLError(FAKE_KEY), TimeoutError(FAKE_KEY), OSError(FAKE_KEY),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(urllib.request.OpenerDirector, "open", side_effect=error) as network:
                with self.assertRaises(DecisionError) as caught:
                    DecisionsClient(FAKE_KEY).create(prepared().payload)
                self.assertNotIn(FAKE_KEY, str(caught.exception))
                network.assert_called_once()
        for body in (FAKE_KEY.encode(), b"\xff", b"[]", b"null"):
            with self.subTest(body=body), patch.object(urllib.request.OpenerDirector, "open", return_value=io.BytesIO(body)) as network:
                with self.assertRaises(DecisionError) as caught:
                    DecisionsClient(FAKE_KEY).create(prepared().payload)
                self.assertNotIn(FAKE_KEY, str(caught.exception))
                network.assert_called_once()

    def test_redirects_never_forward_authorization(self):
        client = DecisionsClient(FAKE_KEY)
        self.assertTrue(any(isinstance(handler, _NoRedirect) for handler in client.opener.handlers))
        request = urllib.request.Request(ENDPOINT, headers={"Authorization": "Bearer " + FAKE_KEY})
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code), self.assertRaises(DecisionError):
                _NoRedirect().redirect_request(request, None, code, FAKE_KEY, {}, "https://other.example")

    def test_invalid_keys_fail_before_a_request(self):
        for key in (None, "", "  ", "key\nvalue"):
            with self.subTest(key=key), self.assertRaises(DecisionError):
                DecisionsClient(key)


if __name__ == "__main__":
    unittest.main()
