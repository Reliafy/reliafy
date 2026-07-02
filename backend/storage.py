"""Content-addressing for dataset files.

Datasets are content-addressed by sha256 so identical uploads de-duplicate to a
single record. The raw bytes themselves are stored inline on the dataset
document in MongoDB (see :mod:`backend.schema`), so this module only needs to
compute the digest.
"""

from __future__ import annotations

import hashlib


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
