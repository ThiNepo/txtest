"""Offline integration tests for the text-test command."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from txtest.cli import main
from txtest.runner import DecisionError


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        previous = Path.cwd()
        os.chdir(directory.name)
        self.addCleanup(os.chdir, previous)
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.dotenv = patch("txtest.cli.find_dotenv", return_value="")
        self.dotenv.start()
        self.addCleanup(self.dotenv.stop)
        Path("file.md").write_text("A lesson with [literal] brackets.", encoding="utf-8")
        Path("txtests/lessons").mkdir(parents=True)

    def write_test(self, name, description=None, kind="predicate", extra=""):
        description = description or f"Description for {name}."
        minimum = "min_probability: 0.5" if kind == "predicate" else "min_score: 4"
        levels = ""
        if kind == "score":
            levels = "levels:\n" + "".join(
                f"  - label: '{index}'\n    description: Level {index}.\n"
                for index in range(1, 6)
            )
        Path(f"txtests/lessons/{name}.txtest").write_text(
            f"---\ndescription: '{description}'\ntype: {kind}\n{minimum}\n"
            f"{levels}{extra}---\n<system>Evaluate the explanation.</system>\n"
            "<user>{{ text }}</user>\n",
            encoding="utf-8",
        )

    def invoke(self):
        return self.runner.invoke(main, ["file.md", "--set", "lessons"], terminal_width=120)

    def test_sorted_sequential_calls_continue_after_failure_and_show_descriptions(self):
        self.write_test("z_last", "Develops the reasoning naturally.")
        self.write_test("a_first", "Explains [what] and [why].")
        with patch("txtest.cli.DecisionsClient") as client:
            def respond(payload):
                name = payload["questions"][0]["name"]
                return {"answers": [{"name": name, "type": "predicate", "probability": 0.3 if name == "a_first" else 0.9}]}

            client.return_value.create.side_effect = respond
            result = self.invoke()
        self.assertEqual(result.exit_code, 1, result.output)
        calls = client.return_value.create.call_args_list
        self.assertEqual([call.args[0]["questions"][0]["name"] for call in calls], ["a_first", "z_last"])
        self.assertIn("Explains [what] and [why].", result.output)
        self.assertIn("Develops the reasoning naturally.", result.output)
        self.assertIn("30%", result.output)
        self.assertIn("90%", result.output)
        self.assertIn("1 passed", result.output)
        self.assertIn("1 failed", result.output)

    def test_api_error_does_not_stop_later_test_and_has_error_exit_code(self):
        self.write_test("a_first")
        self.write_test("b_second")
        with patch("txtest.cli.DecisionsClient") as client:
            client.return_value.create.side_effect = [
                DecisionError("Network request failed."),
                {"answers": [{"name": "b_second", "type": "predicate", "probability": 0.9}]},
            ]
            result = self.invoke()
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertEqual(client.return_value.create.call_count, 2)
        self.assertIn("Network request failed.", result.output)
        self.assertIn("1 passed", result.output)
        self.assertIn("1 error", result.output)

    def test_invalid_definition_does_not_stop_valid_test(self):
        Path("txtests/lessons/a_invalid.txtest").write_text("Missing frontmatter.", encoding="utf-8")
        self.write_test("b_valid")
        with patch("txtest.cli.DecisionsClient") as client:
            client.return_value.create.return_value = {"answers": [{"name": "b_valid", "type": "predicate", "probability": 0.9}]}
            result = self.invoke()
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertEqual(client.return_value.create.call_count, 1)
        self.assertIn("lessons/a_invalid", result.output)
        self.assertIn("Description for b_valid.", result.output)

    def test_no_tests_reports_error_before_credentials_are_loaded(self):
        with patch("txtest.cli._read_api_key") as credentials, patch("txtest.cli.DecisionsClient") as client:
            result = self.invoke()
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("No .txtest files", result.output)
        credentials.assert_not_called()
        client.assert_not_called()

    def test_nested_sets_and_directories_are_rejected(self):
        for set_name in ("..", "../other", "lessons/other", "lessons\\other"):
            with self.subTest(set_name=set_name), patch("txtest.cli.DecisionsClient") as client:
                result = self.runner.invoke(main, ["file.md", "--set", set_name])
                self.assertEqual(result.exit_code, 2, result.output)
                client.assert_not_called()
        result = self.runner.invoke(main, ["txtests", "--set", "lessons"])
        self.assertEqual(result.exit_code, 2, result.output)

    def test_missing_and_whitespace_credentials_are_never_printed(self):
        self.write_test("example")
        for key in ("", "invalid key-value"):
            with self.subTest(key=key), patch.dict(os.environ, {"OPENAI_API_KEY": key}), patch("txtest.cli.DecisionsClient") as client:
                result = self.invoke()
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("OPENAI_API_KEY", result.output)
                if key:
                    self.assertNotIn(key, result.output)
                client.assert_not_called()

    def test_environment_key_takes_precedence_over_dotenv(self):
        self.write_test("example")
        Path(".env").write_text("OPENAI_API_KEY=dotenv-test-key\n", encoding="utf-8")
        with patch("txtest.cli.find_dotenv", return_value=str(Path(".env").resolve())), patch("txtest.cli.DecisionsClient") as client:
            client.return_value.create.return_value = {"answers": [{"name": "example", "type": "predicate", "probability": 0.9}]}
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        client.assert_called_once_with("unit-test-key")

    def test_dotenv_supplies_missing_environment_key(self):
        self.write_test("example")
        Path(".env").write_text("OPENAI_API_KEY=dotenv-test-key\n", encoding="utf-8")
        with patch.dict(os.environ), patch("txtest.cli.find_dotenv", return_value=str(Path(".env").resolve())), patch("txtest.cli.DecisionsClient") as client:
            os.environ.pop("OPENAI_API_KEY", None)
            client.return_value.create.return_value = {"answers": [{"name": "example", "type": "predicate", "probability": 0.9}]}
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        client.assert_called_once_with("dotenv-test-key")

    def test_score_is_shown_on_five_point_scale(self):
        self.write_test("example", kind="score")
        with patch("txtest.cli.DecisionsClient") as client:
            client.return_value.create.return_value = {"answers": [{"name": "example", "type": "score", "score": 3.25}]}
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("4.25 / 5", result.output)
        self.assertIn("4 / 5", result.output)

    def test_near_threshold_failures_show_distinct_values(self):
        for kind, value, display in (("predicate", 0.499999, "49.9999%"),
                                     ("score", 2.99999, "3.99999 / 5")):
            with self.subTest(kind=kind):
                self.write_test("example", kind=kind)
                field = "probability" if kind == "predicate" else "score"
                with patch("txtest.cli.DecisionsClient") as client:
                    client.return_value.create.return_value = {
                        "answers": [{"name": "example", "type": kind, field: value}],
                    }
                    result = self.invoke()
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn(display, result.output)

    def test_template_runtime_error_does_not_stop_later_test(self):
        self.write_test("a_broken")
        path = Path("txtests/lessons/a_broken.txtest")
        path.write_text(path.read_text(encoding="utf-8").replace("{{ text }}", "{{ 1 / 0 }}"), encoding="utf-8")
        self.write_test("b_valid")
        with patch("txtest.cli.DecisionsClient") as client:
            client.return_value.create.return_value = {
                "answers": [{"name": "b_valid", "type": "predicate", "probability": 0.9}],
            }
            result = self.invoke()
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("ZeroDivisionError", result.output)
        self.assertIn("1 passed", result.output)
        client.return_value.create.assert_called_once()

if __name__ == "__main__":
    unittest.main()
