"""Versioned contracts shared by the controller and endpoint adapters."""
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1

class Kind(StrEnum):
    TRANSCRIPT = "transcript"
    IDENTITY = "identity"
    AUDIO = "audio"
    STARTED = "playback_started"
    PLAYED = "played"
    DONE = "done"
    FAILURE = "failure"

@dataclass(frozen=True)
class Token:
    session_id: str
    turn_id: str
    epoch: int
    response_id: str

    def json(self) -> dict:
        return asdict(self)

@dataclass(frozen=True)
class Event:
    kind: Kind
    token: Token
    payload: dict[str, Any]
    event_id: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def make(cls, kind: Kind, token: Token, **payload: Any) -> "Event":
        return cls(kind, token, payload, uuid4().hex)
