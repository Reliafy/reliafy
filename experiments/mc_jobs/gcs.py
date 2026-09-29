"""Just enough Cloud Storage for the worker, on the standard library.

``google-cloud-storage`` pulls in google-auth, api-core and protobuf: seconds
of imports on a cold container. On Cloud Run the metadata server hands out
the job's service-account token, and the JSON API needs nothing more.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


def _token() -> str:
    req = urllib.request.Request(_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["access_token"]


class Bucket:
    def __init__(self, name: str):
        self.name, self.token = name, _token()

    def get(self, path: str) -> bytes:
        url = (f"https://storage.googleapis.com/storage/v1/b/{self.name}/o/"
               f"{urllib.parse.quote(path, safe='')}?alt=media")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def put(self, path: str, data: bytes, content_type: str = "application/json") -> None:
        url = (f"https://storage.googleapis.com/upload/storage/v1/b/{self.name}/o"
               f"?uploadType=media&name={urllib.parse.quote(path, safe='')}")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": content_type})
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
