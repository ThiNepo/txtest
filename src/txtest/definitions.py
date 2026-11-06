"""Load .txtest definitions and render their Jinja templates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

MODEL = "gpt-6-luna"
_FRONTMATTER = re.compile(
    r"\A---[ \t]*\n(?P<header>.*?)^---[ \t]*(?:\n|$)(?P<body>.*)\Z",
    re.MULTILINE | re.DOTALL,
)
_BLOCKS = re.compile(
    r"\A\s*<system>(?P<instructions>.*?)</system>"
    r"\s*<user>(?P<input>.*?)</user>\s*\Z",
    re.DOTALL,
)
_KEYS = {"description", "type", "min_score", "min_probability", "levels", "model"}


class DefinitionError(ValueError):
    """A test cannot be loaded or rendered."""


@dataclass(frozen=True)
class PreparedTest:
    name: str
    description: str
    kind: str
    minimum: float
    payload: dict[str, Any]

    @classmethod
    def load(cls, path: Path, text: str, source: Path) -> PreparedTest:
        """Read YAML frontmatter and render separate instruction and input blocks.

        Parse the blocks before interpolating text, so markup in an input file cannot
        become template structure. Missing Jinja variables fail before any API call.
        """
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            raise DefinitionError("Could not read the test as UTF-8 text.") from None
        match = _FRONTMATTER.fullmatch(content)
        if not match:
            raise DefinitionError("Start the file with YAML frontmatter enclosed by '---' lines.")
        try:
            config = yaml.safe_load(match["header"])
        except yaml.YAMLError:
            raise DefinitionError("The YAML frontmatter is invalid.") from None
        if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
            raise DefinitionError("The YAML frontmatter must contain named configuration fields.")
        if unknown := set(config) - _KEYS:
            raise DefinitionError(f"Unknown configuration fields: {', '.join(sorted(unknown))}.")
        description = config.get("description")
        if not isinstance(description, str) or not description.strip():
            raise DefinitionError("Provide a short, nonempty 'description' for the terminal output.")
        kind = config.get("type", "score")
        if kind not in ("predicate", "score"):
            raise DefinitionError("'type' must be 'predicate' or 'score'.")
        if config.get("model", MODEL) != MODEL:
            raise DefinitionError(f"The Decisions API model must be '{MODEL}'.")

        question: dict[str, Any] = {"type": kind, "name": path.stem}
        if kind == "predicate":
            if "min_score" in config or "levels" in config:
                raise DefinitionError("Use 'min_probability' for a predicate test.")
            minimum = _number(config.get("min_probability", 0.5), "min_probability", 0, 1)
        else:
            if "min_probability" in config:
                raise DefinitionError("Use 'min_score' for a score test.")
            minimum = _number(config.get("min_score", 4), "min_score", 1, 5)
            question["levels"] = _score_levels(config.get("levels"))

        blocks = _BLOCKS.fullmatch(match["body"])
        if not blocks:
            raise DefinitionError("Follow the header with one <system> block and one <user> block.")
        environment = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        context = {"text": text, "filename": source.name, "path": str(source)}
        try:
            instructions = environment.from_string(blocks["instructions"].strip()).render(context)
            evidence = environment.from_string(blocks["input"].strip()).render(context)
        except Exception as error:
            # User-written Jinja expressions may also raise Python exceptions.
            raise DefinitionError(f"Could not render the Jinja template ({type(error).__name__}).") from None
        if not instructions.strip() or not evidence.strip():
            raise DefinitionError("The rendered instructions and input must both be nonempty.")
        question["instructions"] = instructions
        return cls(
            name=path.stem,
            description=" ".join(description.split()),
            kind=kind,
            minimum=minimum,
            payload={"model": MODEL, "input": evidence, "questions": [question]},
        )


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DefinitionError(f"'{name}' must be a number from {low:g} to {high:g}.")
    if not low <= value <= high:
        raise DefinitionError(f"'{name}' must be a number from {low:g} to {high:g}.")
    return float(value)


def _score_levels(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) != 5:
        raise DefinitionError("A score test requires exactly five ordered 'levels'.")
    levels = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"label", "description"}:
            raise DefinitionError("Each level needs a 'label' and a 'description'.")
        if any(not isinstance(item[key], str) or not item[key].strip() for key in item):
            raise DefinitionError("Level labels and descriptions must be nonempty strings.")
        levels.append({key: item[key].strip() for key in ("label", "description")})
    if len({level["label"] for level in levels}) != 5:
        raise DefinitionError("Each score level must have a unique label.")
    return levels
