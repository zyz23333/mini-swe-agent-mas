"""MAS command classification for bash-shaped model actions."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum

MAS_COMMAND_NAME = "mini-mas"
STANDALONE_CORRECTION = "mini-mas must be issued as a standalone command, not inside shell composition."
SHELL_CONTROL_TOKENS = frozenset(
    {
        "&",
        "&&",
        "(",
        ")",
        ";",
        ";;",
        ";&",
        ";;&",
        "<",
        "<<",
        "<<<",
        ">",
        ">>",
        "|",
        "|&",
        "||",
    }
)
SHELL_KEYWORDS = frozenset({"case", "do", "done", "elif", "else", "esac", "fi", "for", "if", "then", "until", "while"})


class MasCommandKind(str, Enum):
    """Routing decision for a bash-shaped model command."""

    STANDALONE = "standalone"
    ORDINARY_BASH = "ordinary_bash"
    INVALID = "invalid"


@dataclass(frozen=True)
class MasCommandClassification:
    """Parsed MAS command routing result."""

    kind: MasCommandKind
    command: str
    arguments: list[str]
    error: str = ""


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _is_environment_assignment(token: str) -> bool:
    name, separator, _value = token.partition("=")
    return bool(separator) and name.isidentifier()


def _contains_shell_composition(tokens: list[str]) -> bool:
    return any(
        token in SHELL_CONTROL_TOKENS or token in SHELL_KEYWORDS or _is_environment_assignment(token)
        for token in tokens
    )


def classify_mas_command(command: str) -> MasCommandClassification:
    """Classify a bash-shaped action command before Agent Workflow execution."""
    stripped_command = command.strip()
    if MAS_COMMAND_NAME not in stripped_command:
        return MasCommandClassification(
            kind=MasCommandKind.ORDINARY_BASH,
            command=stripped_command,
            arguments=[],
        )

    try:
        tokens = _shell_tokens(stripped_command)
    except ValueError as exc:
        return MasCommandClassification(
            kind=MasCommandKind.INVALID,
            command=stripped_command,
            arguments=[],
            error=f"{STANDALONE_CORRECTION} Could not parse command: {exc}",
        )

    if tokens and tokens[0] == MAS_COMMAND_NAME and MAS_COMMAND_NAME not in tokens[1:] and not _contains_shell_composition(tokens):
        return MasCommandClassification(
            kind=MasCommandKind.STANDALONE,
            command=stripped_command,
            arguments=tokens[1:],
        )

    if MAS_COMMAND_NAME in tokens or MAS_COMMAND_NAME in stripped_command:
        return MasCommandClassification(
            kind=MasCommandKind.INVALID,
            command=stripped_command,
            arguments=[],
            error=STANDALONE_CORRECTION,
        )

    return MasCommandClassification(
        kind=MasCommandKind.ORDINARY_BASH,
        command=stripped_command,
        arguments=[],
    )
