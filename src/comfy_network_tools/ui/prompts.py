"""Prompt abstraction so screens can be driven by a scripted fake in tests.

A returned ``None`` from :meth:`Prompter.select` / :meth:`text` / :meth:`password`
means "the user backed out" (Esc / Ctrl+C at that prompt).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

Choice = tuple[str, object]  # (label shown, value returned)


def _as_choices(options: Sequence[Choice | str]) -> list[Choice]:
    out: list[Choice] = []
    for option in options:
        if isinstance(option, str):
            out.append((option, option))
        else:
            out.append((option[0], option[1]))
    return out


class Prompter(ABC):
    @abstractmethod
    def select(self, message: str, options: Sequence[Choice | str]) -> object | None: ...

    @abstractmethod
    def checkbox(self, message: str, options: Sequence[Choice | str]) -> list[object]: ...

    @abstractmethod
    def text(self, message: str, *, default: str = "") -> str | None: ...

    @abstractmethod
    def password(self, message: str) -> str | None: ...

    @abstractmethod
    def confirm(self, message: str, *, default: bool = False) -> bool: ...


def host_key_prompt(prompter: Prompter, console):
    """A callback for `ssh.connect`: show an unknown host key fingerprint, ask to trust it."""

    def prompt(host, fingerprint: str) -> bool:
        console.print(
            f"[yellow]Host {host.name} ({host.address}:{host.port}) key is not trusted.[/]\n"
            f"  SHA256 fingerprint: [bold]{fingerprint}[/]"
        )
        return prompter.confirm("Trust this host key and pin it?", default=False)

    return prompt


class QuestionaryPrompter(Prompter):
    def select(self, message, options):
        import questionary

        choices = _as_choices(options)
        answer = questionary.select(
            message, choices=[questionary.Choice(title=c[0], value=c[1]) for c in choices]
        ).ask()
        return answer

    def checkbox(self, message, options):
        import questionary

        choices = _as_choices(options)
        answer = questionary.checkbox(
            message, choices=[questionary.Choice(title=c[0], value=c[1]) for c in choices]
        ).ask()
        return answer or []

    def text(self, message, *, default=""):
        import questionary

        return questionary.text(message, default=default).ask()

    def password(self, message):
        import questionary

        return questionary.password(message).ask()

    def confirm(self, message, *, default=False):
        import questionary

        answer = questionary.confirm(message, default=default).ask()
        return bool(answer)
