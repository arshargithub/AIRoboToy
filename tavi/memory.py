"""Offline outbox rehearsal. This does not extract or infer real memories."""
from .storage import Store

class FakeMemory:
    def __init__(self, store: Store):
        self.store = store

    def ingest(self, source_id: str, body: dict) -> None:
        self.store.record("fake-memory:" + source_id, {"kind": "fake_projection", "source_id": source_id, "evidence": body})

def drain_outbox(store: Store, adapter: FakeMemory, limit: int = 100) -> dict:
    successes = failures = 0
    for job in store.pending()[:limit]:
        try:
            adapter.ingest(job["id"], job["body"])
        except (RuntimeError, OSError):
            store.attempt(job["id"], succeeded=False)
            failures += 1
        else:
            store.attempt(job["id"], succeeded=True)
            successes += 1
    return {"successes": successes, "failures": failures}
