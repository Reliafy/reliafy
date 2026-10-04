"""Upload chunks belong to the PUT that sent them; a slot still receiving
isn't taken over within the request timeout."""

import hashlib
from datetime import timedelta

import mongomock

from backend.services import uploads


def test_a_taken_over_upload_keeps_only_the_new_puts_chunks():
    db = mongomock.MongoClient()["uploads"]
    doc, _ = uploads.create(db, "u1", "rbd_import", "plant.dft")
    first = uploads.claim(db, doc["_id"])
    uploads.write_chunk(db, doc["_id"], 0, b"AAAA", first["claim"])
    # The first PUT stalls past the stale limit; a second one takes the slot over.
    db.uploads.update_one({"_id": doc["_id"]},
                          {"$set": {"receiving_since": first["receiving_since"] - uploads.STALE_RECEIVING
                                    - timedelta(seconds=1)}})
    second = uploads.claim(db, doc["_id"])
    assert second is not None and second["claim"] != first["claim"]
    uploads.write_chunk(db, doc["_id"], 0, b"BB", second["claim"])
    uploads.write_chunk(db, doc["_id"], 1, b"AAAA", first["claim"])  # the stalled PUT carries on
    assert uploads.finish(db, doc["_id"], first["claim"], 8, hashlib.sha256(b"A" * 8).hexdigest(), b"") is None
    out = uploads.finish(db, doc["_id"], second["claim"], 2, hashlib.sha256(b"BB").hexdigest(), b"BB")
    assert out is not None
    # The stalled PUT's late release doesn't touch the new file either.
    uploads.release(db, doc["_id"], first["claim"])
    got, data = uploads.read(db, doc["_id"], "u1")
    assert data == b"BB" and got["status"] == "ready"


def test_a_receiving_slot_is_not_taken_over_within_the_request_timeout():
    assert uploads.STALE_RECEIVING.total_seconds() > 600
    db = mongomock.MongoClient()["uploads"]
    doc, _ = uploads.create(db, "u1", "rbd_import", "plant.dft")
    assert uploads.claim(db, doc["_id"]) is not None
    assert uploads.claim(db, doc["_id"]) is None
