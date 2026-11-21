from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIError(RuntimeError):
    """Provider unreachable, timed out, or returned unusable output."""


@dataclass
class Usage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    calls: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.seconds += other.seconds
        self.calls += other.calls
        self.notes += other.notes


class Provider(Protocol):
    name: str
    model: str

    def complete_json(
        self, system: str, user: str, schema: type[T], *, timeout: float
    ) -> tuple[T, Usage]:
        """One request; returns a validated object or raises AIError."""
        ...

    def health(self) -> tuple[bool, str]:
        """Cheap check that the provider is reachable and the model exists."""
        ...
