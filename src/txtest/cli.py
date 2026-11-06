"""Run a set of text tests and display their results in the terminal."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import click
from dotenv import find_dotenv, load_dotenv
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from . import __version__
from .definitions import DefinitionError, PreparedTest
from .runner import DecisionsClient, TestResult, TestRunner


class CommandError(click.ClickException):
    """An execution error, distinct from a failed text assertion."""

    exit_code = 2


@dataclass
class _Row:
    identifier: str
    description: str
    test: PreparedTest | None = None
    result: TestResult | None = None
    error: str | None = None
    running: bool = False

    @property
    def status(self) -> str:
        if self.error is not None:
            return "ERROR"
        if self.result is not None:
            return self.result.status
        return "RUNNING" if self.running else "PENDING"


def _discover_tests(set_name: str) -> list[Path]:
    if (
        not set_name.strip()
        or set_name in {".", ".."}
        or any(character in set_name for character in ("/", "\\", ":"))
    ):
        raise CommandError("--set must be a single folder name inside txtests.")
    root = (Path.cwd() / "txtests").resolve()
    directory = (root / set_name).resolve()
    if not directory.is_relative_to(root):
        raise CommandError("The test set must stay inside the txtests folder.")
    if not directory.is_dir():
        raise CommandError(f"Test set not found: txtests/{set_name}.")
    try:
        paths = sorted(
            (path for path in directory.glob("*.txtest") if path.is_file()),
            key=lambda path: path.name,
        )
    except OSError:
        raise CommandError(f"Could not read test set: txtests/{set_name}.") from None
    if not paths:
        raise CommandError(f"No .txtest files found in txtests/{set_name}.")
    return paths


def _read_api_key() -> str:
    try:
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path, override=False)
    except (OSError, UnicodeError):
        raise CommandError("Could not read the .env file.") from None
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key.strip():
        raise CommandError("Set OPENAI_API_KEY in your environment or a .env file.")
    if any(character.isspace() for character in key):
        raise CommandError("OPENAI_API_KEY must not contain whitespace.")
    return key


def _metric(value: float, kind: str) -> str:
    # Preserve threshold differences without binary-float percentage artifacts.
    number = Decimal(str(value)) * (100 if kind == "predicate" else 1)
    display = format(number.normalize(), "f")
    return f"{display}%" if kind == "predicate" else f"{display} / 5"


def _table(rows: list[_Row]) -> Table:
    table = Table(
        box=box.SIMPLE,
        expand=True,
        show_edge=False,
        pad_edge=False,
        header_style="bold dim",
        padding=(0, 1),
    )
    table.add_column("Test", ratio=1)
    table.add_column("Result", no_wrap=True)
    table.add_column("Value", justify="right", no_wrap=True)
    table.add_column("Minimum", justify="right", no_wrap=True)
    styles = {
        "PASS": "bold green",
        "FAIL": "bold red",
        "ERROR": "bold yellow",
        "RUNNING": "cyan",
        "PENDING": "dim",
    }
    for row in rows:
        label = Text(row.identifier, style="bold")
        label.append("\n" + row.description, style="dim")
        error = row.error or (row.result.error if row.result else None)
        if error:
            label.append("\n" + error, style="yellow")
        value = "—"
        minimum = "—"
        if row.test is not None:
            minimum = _metric(row.test.minimum, row.test.kind)
            if row.result is not None and row.result.value is not None:
                value = _metric(row.result.value, row.test.kind)
        table.add_row(
            label,
            Text(row.status, style=styles[row.status]),
            Text(value),
            Text(minimum),
            end_section=True,
        )
    return table


def _execute(rows: list[_Row], runner: TestRunner, console: Console) -> None:
    with Live(_table(rows), console=console, refresh_per_second=8) as live:
        for row in rows:
            if row.test is None or row.error is not None:
                continue
            row.running = True
            message = Text("Evaluating ", style="cyan")
            message.append(row.identifier)
            live.update(Group(_table(rows), Spinner("dots", text=message)), refresh=True)
            row.result = runner.run(row.test)
            row.running = False
            live.update(_table(rows), refresh=True)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument(
    "file",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option("--set", "test_set", required=True, metavar="NAME", help="Test set in txtests/NAME.")
@click.version_option(version=__version__, prog_name="txtest")
@click.pass_context
def main(ctx: click.Context, file: Path, test_set: str) -> None:
    """Evaluate FILE against every .txtest in the selected set.

    Each test runs once. Results stay in the terminal.
    """
    paths = _discover_tests(test_set)
    try:
        text = file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise CommandError(f"Could not read {file} as UTF-8 text.") from None

    rows = []
    for path in paths:
        identifier = f"{test_set}/{path.stem}"
        try:
            test = PreparedTest.load(path, text, file)
        except (DefinitionError, OSError, UnicodeError) as error:
            rows.append(_Row(identifier, "Invalid test configuration.", error=str(error)))
        else:
            rows.append(_Row(identifier, test.description, test=test))

    console = Console(highlight=False)
    heading = Text(str(file), style="bold")
    heading.append(f"\nSet: {test_set}  ·  {len(rows)} test{'s' if len(rows) != 1 else ''}", style="dim")
    console.print(Panel(heading, title=Text("txtest", style="bold cyan"), border_style="cyan"))

    if any(row.test is not None for row in rows):
        try:
            client = DecisionsClient(_read_api_key())
        except (CommandError, ValueError) as error:
            for row in rows:
                if row.test is not None:
                    row.error = str(error)
            console.print(_table(rows))
        else:
            _execute(rows, TestRunner(client), console)
    else:
        console.print(_table(rows))

    passed = sum(row.status == "PASS" for row in rows)
    failed = sum(row.status == "FAIL" for row in rows)
    errors = sum(row.status == "ERROR" for row in rows)
    console.print()
    summary = Text()
    summary.append(f"{passed} passed", style="green")
    summary.append("  ·  ")
    summary.append(f"{failed} failed", style="red" if failed else "dim")
    summary.append("  ·  ")
    summary.append(f"{errors} error{'s' if errors != 1 else ''}", style="yellow" if errors else "dim")
    console.print(summary)
    ctx.exit(2 if errors else 1 if failed else 0)
