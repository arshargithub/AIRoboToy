"""Serial event reducer. Only the service event loop may mutate it."""
from collections import deque
from dataclasses import asdict
import time
from uuid import uuid4
from .contracts import Event, Kind, SCHEMA_VERSION, Token
from .storage import Store

class Controller:
    def __init__(self, store: Store, *, max_queue_ms: int = 2000, simulation: bool = True,
                 record_sources: bool = True, require_playback_start: bool = False):
        if max_queue_ms <= 0:
            raise ValueError("Playback limit must be positive")
        self.store = store
        self.simulation = simulation
        self.record_sources = record_sources
        self.require_playback_start = require_playback_start
        self._playback_started = False
        self.max_queue_ms = max_queue_ms
        self.session_id = uuid4().hex
        self.epoch = 0
        self.token: Token | None = None
        self.engagement = "idle"
        self.input = "wake_only"
        self.output = "silent"
        self.connectivity = "ready"
        self.error: str | None = None
        self.queue: deque[dict] = deque()
        self._seen: set[str] = set()
        self._transcript: str | None = None
        self._speaker: str | None = None
        self._ready = False
        self._done = False
        self._last_chunk = -1
        self.revision = 0
        self.rejected_events = 0

    def _touch(self):
        self.revision += 1

    def cancel(self, reason: str = "interrupted") -> None:
        if self.token and self.record_sources:
            self.store.record(self.token.turn_id + ":cancel", {"kind": "cancelled", "token": asdict(self.token), "reason": reason})
        self.epoch += 1
        self.token = None
        self.queue.clear()
        self._seen.clear()
        self.output = "silent"
        self._playback_started = False
        self.input = "muted" if self.input == "muted" else "wake_only"
        self._touch()

    def begin(self) -> Token:
        if self.input == "muted" or self.connectivity == "offline":
            raise ValueError("Unmute and restore connectivity before a simulated turn")
        self.cancel()
        self.token = Token(self.session_id, uuid4().hex, self.epoch, uuid4().hex)
        self.engagement = "active"
        self.input = "capturing"
        self.error = None
        self._transcript = self._speaker = None
        self._ready = self._done = False
        self._last_chunk = -1
        return self.token

    def mute(self, value: bool) -> None:
        self.cancel("mute" if value else "unmute")
        self.input = "muted" if value else "wake_only"
        self.engagement = "idle"

    def end(self) -> None:
        self.cancel("session ended")
        self.engagement = "idle"
        self.session_id = uuid4().hex

    def connected(self, value: bool) -> None:
        self.cancel("connection changed")
        self.connectivity = "ready" if value else "offline"
        self.engagement = "idle"

    def _reject(self) -> bool:
        self.rejected_events += 1
        return False

    def apply(self, event: Event) -> bool:
        if event.schema_version != SCHEMA_VERSION or event.token != self.token or self.token is None:
            return self._reject()
        if event.event_id in self._seen:
            return self._reject()
        p = event.payload
        # Validate before mutation. Bad adapters must not corrupt the reducer.
        if event.kind == Kind.TRANSCRIPT:
            if self._transcript is not None or not isinstance(p.get("text"), str) or not p["text"].strip() or len(p["text"]) > 2000:
                return self._reject()
            self._transcript = p["text"].strip()
        elif event.kind == Kind.IDENTITY:
            if self._speaker is not None or p.get("speaker") not in ("unknown", "adultone", "adulttwo", "childtwo", "childone"):
                return self._reject()
            self._speaker = p["speaker"]
        elif event.kind == Kind.AUDIO:
            if not self._ready or self._done or type(p.get("sequence")) is not int or p["sequence"] != self._last_chunk + 1:
                return self._reject()
            if type(p.get("duration_ms")) is not int or p["duration_ms"] <= 0 or not isinstance(p.get("text"), str):
                return self._reject()
            if sum(c["duration_ms"] for c in self.queue) + p["duration_ms"] > self.max_queue_ms:
                self.error = "Playback queue overflow; response cancelled"
                self.cancel("queue overflow")
                return False
            self.queue.append(dict(p))
            self._last_chunk = p["sequence"]
            self.output = "playing" if not self.require_playback_start or self._playback_started else "ready"
        elif event.kind == Kind.STARTED:
            if not self.require_playback_start or self._playback_started or not self.queue or p.get("sequence") != self.queue[0]["sequence"]:
                return self._reject()
            self._playback_started = True
            self.output = "playing"
        elif event.kind == Kind.PLAYED:
            # Acknowledge complete chunks only, in endpoint playback order.
            if not self.queue or p.get("sequence") != self.queue[0]["sequence"] or (self.require_playback_start and not self._playback_started):
                return self._reject()
            chunk = self.queue.popleft()
            if self.record_sources:
                self.store.record(f"{self.token.turn_id}:assistant:{chunk['sequence']}", {
                    "kind": "assistant_played", "token": asdict(self.token), "text": chunk["text"],
                    "duration_ms": chunk["duration_ms"], "event_time": time.time()})
            self._playback_started = False
            self.output = ("ready" if self.require_playback_start else "playing") if self.queue else ("silent" if self._done else "generating")
        elif event.kind == Kind.DONE:
            if not self._ready or self._done:
                return self._reject()
            self._done = True
            if not self.queue:
                self.output = "silent"
        elif event.kind == Kind.FAILURE:
            self.error = "Simulated provider failure" if self.simulation else "Provider failure"
            self.cancel("provider failure")
            self.connectivity = "degraded"
        else:
            return self._reject()
        self._seen.add(event.event_id)
        if not self._ready and self._transcript is not None and self._speaker is not None:
            if self.record_sources:
                self.store.record(self.token.turn_id + ":user", {
                    "kind": "user_utterance", "token": asdict(self.token), "text": self._transcript,
                    "speaker": self._speaker, "event_time": time.time(), "simulation": self.simulation},
                    memory=self._speaker != "unknown")
            self._ready = True
            self.input = "wake_only"
            self.output = "generating"
        self._touch()
        return True

    def snapshot(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "revision": self.revision,
                "engagement": self.engagement, "input": self.input, "output": self.output,
                "connectivity": self.connectivity, "token": asdict(self.token) if self.token else None,
                "error": self.error, "queued_ms": sum(c["duration_ms"] for c in self.queue),
                "rejected_events": self.rejected_events, "simulation": self.simulation,
                "speaker": self._speaker if self.token else None,
                "transcript": self._transcript if self.token else None}
