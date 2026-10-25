"""The Reliafy API client: every tool action, files, photos and ingest.

    from reliafy import Client

    rf = Client(token="rlf_...")                       # or RELIAFY_TOKEN / reliafy login
    rf.call("list", "models")                          # any tool action: POST /api/v1/list/models
    rf.call("life_data_analysis", "fit", data=[120, 340, 510], censored=[0, 0, 1])
    rf.call("guide", topic="life_data")                # a tool without actions

Every Reliafy MCP tool action is callable with :meth:`Client.call`, with the
same arguments and results as over MCP. ``GET /api/v1/tools`` (``rf.tools()``)
lists them; ``rf.spec()`` is the OpenAPI spec. Pure standard library.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

DEFAULT_BASE = "https://reliafy.com"
USER_AGENT = "reliafy-client/{version}"
#: The tools API this client needs (``api`` in ``GET /api/v1/tools``).
NEEDS_API = 1
OLD_SERVER = (
    "This Reliafy server doesn't have the tools API (POST /api/v1/{{tool}}/{{action}}), which reliafy-client "
    "{version} needs for this. It's on reliafy.com from the release that adds it; a self-hosted server needs "
    "updating. The 0.2 functions (reliafy.models.*, reliafy.data.*, reliafy.strategy.*, reliafy.fleet.*) "
    "still work against it.")
_FINISHED = ("done", "failed", "error", "cancelled", "canceled", "expired")


class ReliafyError(RuntimeError):
    """A refused or failed call. ``status`` is the HTTP status (None when the
    server couldn't be reached); ``detail`` is the server's message."""

    def __init__(self, message: str, status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail if detail is not None else message


class ServerTooOld(ReliafyError):
    """The server predates the tools API."""


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("reliafy-client")
    except Exception:  # noqa: BLE001
        return "0.3.1"


class Client:
    """A connection to one Reliafy server as one user.

    ``token``: an API token (``rlf_…``, Settings > API access); defaults to
    ``RELIAFY_TOKEN``, then the token saved by ``reliafy login``.
    ``base_url``: defaults to ``RELIAFY_BASE_URL``, the saved one, then
    https://reliafy.com. A local server with sign-in off needs no token.
    """

    def __init__(self, token: str | None = None, base_url: str | None = None, timeout: float = 120.0):
        saved = {}
        if token is None or base_url is None:
            from reliafy import config as _config

            saved = _config.load()
        self.token = token if token is not None else (os.environ.get("RELIAFY_TOKEN") or saved.get("token"))
        self.base_url = (base_url or os.environ.get("RELIAFY_BASE_URL") or saved.get("base_url")
                         or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self._spec: dict | None = None

    def __repr__(self) -> str:
        return f"<reliafy.Client {self.base_url}>"

    # ---- transport ---------------------------------------------------------------

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": USER_AGENT.format(version=_version()), "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(extra or {})
        return h

    def request(self, method: str, path: str, payload: Any = None, *, data: Any = None,
                headers: dict | None = None, auth: bool = True, url: str | None = None) -> Any:
        """One HTTP request; JSON in (``payload``) or raw bytes / a file
        (``data``), JSON out. Raises :class:`ReliafyError`."""
        target = url or (self.base_url + path)
        hdrs = self._headers(headers) if auth else {"User-Agent": USER_AGENT.format(version=_version()),
                                                    **(headers or {})}
        if payload is not None:
            data = json.dumps(payload).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(target, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                detail = json.loads(body).get("detail", exc.reason)
            except Exception:  # noqa: BLE001
                detail = exc.reason
            raise ReliafyError(f"Reliafy returned {exc.code}: {detail}", exc.code, detail) from None
        except urllib.error.URLError as exc:
            raise ReliafyError(f"Couldn't reach Reliafy at {target}: {exc.reason}") from None
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            raise ReliafyError(f"Reliafy at {target} didn't answer with JSON (is the base URL right?).") from None

    def _tools_api(self, exc: ReliafyError) -> ReliafyError:
        """A 404/405 from a tools route: a server without the tools API, or a
        real "no such tool" from one that has it."""
        if exc.status in (404, 405) and exc.detail in ("Not Found", "Method Not Allowed", "Not found."):
            try:
                self.request("GET", "/api/v1/tools")
            except ReliafyError as probe:
                if probe.status in (404, 405):
                    return ServerTooOld(OLD_SERVER.format(version=_version()), probe.status, probe.detail)
        return exc

    # ---- the tools -----------------------------------------------------------

    def call(self, tool: str, action: str | None = None, /, wait: bool | float = False, **args) -> Any:
        """Call a tool action with its arguments (``None`` values are left
        out). ``action`` is the tool's action (or kind); omit it for a tool
        without actions. ``wait=True`` (or a number of seconds) polls a
        long-running result's ``job_id`` until it finishes."""
        args = {k: v for k, v in args.items() if v is not None}
        path = f"/api/v1/{urllib.parse.quote(tool)}" + (f"/{urllib.parse.quote(action)}" if action else "")
        try:
            out = self.request("POST", path, args)
        except ReliafyError as exc:
            raise self._tools_api(exc) from None
        if wait and isinstance(out, dict) and out.get("job_id") and out.get("status") not in _FINISHED:
            out = self.wait(out["job_id"], timeout=None if wait is True else float(wait))
        return out

    def wait(self, job_id: str, timeout: float | None = None, every: float = 2.0) -> dict:
        """Poll a job (``get`` kind ``job``) until it finishes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        delay = 1.0
        while True:
            job = self.call("get", "job", id=job_id)
            if not isinstance(job, dict) or not job.get("job_id") or job.get("status") in _FINISHED:
                return job
            if deadline is not None and time.monotonic() >= deadline:
                return job
            time.sleep(delay)
            delay = min(delay * 1.5, every * 3)

    def tools(self) -> dict:
        """The tools and actions you may call (``GET /api/v1/tools``)."""
        try:
            return self.request("GET", "/api/v1/tools")
        except ReliafyError as exc:
            if exc.status in (404, 405):
                raise ServerTooOld(OLD_SERVER.format(version=_version()), exc.status, exc.detail) from None
            raise

    def spec(self, refresh: bool = False) -> dict:
        """The OpenAPI spec of what you may call (``GET /api/v1/openapi.json``)."""
        if self._spec is None or refresh:
            try:
                self._spec = self.request("GET", "/api/v1/openapi.json")
            except ReliafyError as exc:
                if exc.status in (404, 405):
                    raise ServerTooOld(OLD_SERVER.format(version=_version()), exc.status, exc.detail) from None
                raise
        return self._spec

    # ---- typed shortcuts for the common things -----------------------------------

    def list(self, kind: str, **args) -> dict:
        """``list`` kind (models, datasets, rbds, fleets, …)."""
        return self.call("list", kind, **args)

    def get(self, kind: str, id: str | None = None, **args) -> dict:
        """``get`` kind by id (model, dataset, rbd, job, upload, account, …)."""
        return self.call("get", kind, id=id, **args)

    def fit(self, data=None, *, distribution: str | None = None, censored=None, dataset_id: str | None = None,
            save_as: str | None = None, **args) -> dict:
        """Fit a life distribution to inline ``data`` (with ``censored`` flags:
        0 failed, 1 still running) or a saved ``dataset_id``. ``save_as``
        names and saves the model (``models fit``); without it nothing is saved."""
        if save_as:
            return self.call("models", "fit", name=save_as, data=data, distribution=distribution,
                             censored=censored, dataset_id=dataset_id, **args)
        return self.call("life_data_analysis", "fit", data=data, distribution=distribution,
                         censored=censored, dataset_id=dataset_id, **args)

    def reliability(self, model_id: str, times, **args) -> dict:
        """Reliability (and more) of a saved model at times."""
        return self.call("life_data_analysis", "reliability_at", model_id=model_id,
                         times=list(times) if isinstance(times, (list, tuple)) else [times], **args)

    def guide(self, topic: str | None = None) -> dict:
        return self.call("guide", topic=topic)

    # ---- files (REST only: MCP can't carry bytes) -----------------------------

    def upload_file(self, path: str, purpose: str) -> dict:
        """Send a file to Reliafy without reading it into memory: ``uploads
        create``, then the file streamed to the single-use link. Returns the
        upload (``upload_id``…), ready to import. ``purpose``: dataset,
        excel, rbd_import, outage_log or document (a PDF)."""
        size = os.path.getsize(path)
        link = self.call("uploads", "create", purpose=purpose, filename=os.path.basename(path), size_bytes=size)
        last: ReliafyError | None = None
        urls = [u for u in (link["url"], link.get("url_fallback")) if u]
        # The links are only used when one of them is on this server (its fast
        # direct address, then the public one); a server that names another
        # host (a self-hosted install without PUBLIC_BASE_URL) gets the file at
        # the same path on the address this client talks to, never elsewhere.
        if _origin(self.base_url) not in {_origin(u) for u in urls}:
            parts = urllib.parse.urlsplit(link["url"])
            urls = [f"{self.base_url}{parts.path}?{parts.query}"]
        for url in urls:
            if not url:
                continue
            try:
                with open(path, "rb") as fh:
                    self.request("PUT", "", data=fh, url=url, auth=False, headers={
                        "Content-Type": "application/octet-stream", "Content-Length": str(size)})
                return {"upload_id": link["upload_id"], "filename": os.path.basename(path), "size_bytes": size}
            except ReliafyError as exc:
                last = exc
                if exc.status is not None:  # the server answered: retrying elsewhere won't help
                    break
        raise last or ReliafyError("The upload failed.")

    def upload_dataset(self, path: str, name: str | None = None, sheet: str | None = None, **args) -> dict:
        """Upload a CSV or .xlsx file as a dataset."""
        up = self.upload_file(path, "dataset")
        return self.call("datasets", "upload", upload_id=up["upload_id"],
                         name=name or os.path.splitext(os.path.basename(path))[0], sheet=sheet, **args)

    def import_rbd(self, path: str, **args) -> dict:
        """Import a diagram file (BlockSim .rsgz/.rsr, Open-PSA .xml, Galileo
        .dft, RePyability .json) as RBDs."""
        up = self.upload_file(path, "rbd_import")
        return self.call("uploads", "import_rbd", upload_id=up["upload_id"], **args)

    def import_excel(self, path: str, **args) -> dict:
        """Import an .xlsx workbook (a data sheet, an RCM/FMEA worksheet or
        Reliafy's RBD template): see the uploads guide for the arguments. An
        RCM worksheet needs ``target="rcm", position_id=…``."""
        up = self.upload_file(path, "excel")
        return self.call("uploads", "import_excel", upload_id=up["upload_id"], **args)

    def add_photo(self, path: str, target_id: str, caption: str | None = None) -> dict:
        """Add a photo (JPEG, PNG, HEIC, …) to a maintenance position, item,
        location or work order, streamed from disk. Reliafy Maintenance only."""
        size = os.path.getsize(path)
        query = urllib.parse.urlencode({"target_id": target_id, **({"caption": caption} if caption else {})})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            try:
                return self.request("POST", f"/api/v1/maintenance/photos?{query}", data=fh, headers={
                    "Content-Type": ctype, "Content-Length": str(size)})
            except ReliafyError as exc:
                raise self._tools_api(exc) from None

    def add_document(self, path: str, target_id: str | None = None, *, position_class: str | None = None,
                     title: str | None = None, kind: str | None = None) -> dict:
        """Keep a PDF (at most 20 MB) on a maintenance item or position
        (``target_id``) or a position class, streamed from disk. ``kind``:
        manual, datasheet, invoice, drawing, certificate or other. Reliafy
        Maintenance only."""
        up = self.upload_file(path, "document")
        return self.call("maintenance_attachments", "add_document", upload_id=up["upload_id"], target_id=target_id,
                         position_class=position_class, title=title, kind=kind)

    def download_document(self, document_id: str, path: str | None = None) -> str:
        """Save a PDF kept in Reliafy Maintenance to ``path`` (default: its own
        file name, in the current folder). Returns the path written."""
        doc = self.call("maintenance_get", "document", id=document_id)
        url = doc.get("download_url")
        if not url:
            raise ReliafyError("That document is a link, not a stored PDF: open its url instead.")
        if _origin(url) != _origin(self.base_url):  # only ever from the server this client talks to
            parts = urllib.parse.urlsplit(url)
            url = f"{self.base_url}{parts.path}?{parts.query}"
        target = path or os.path.basename(doc.get("file_name") or f"{document_id}.pdf")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT.format(version=_version())})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp, open(target, "wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
        except urllib.error.HTTPError as exc:
            raise ReliafyError(f"Reliafy returned {exc.code} for the document.", exc.code) from None
        except urllib.error.URLError as exc:
            raise ReliafyError(f"Couldn't reach Reliafy at {url.split('?')[0]}: {exc.reason}") from None
        return target

    # ---- ingest (the ingest scope) -----------------------------------------

    def _ingest(self, path: str, rows=None, csv: str | None = None, file: str | None = None, key: str = "rows"):
        if file is not None:
            size = os.path.getsize(file)
            with open(file, "rb") as fh:
                return self.request("POST", path, data=fh, headers={
                    "Content-Type": "text/csv", "Content-Length": str(size)})
        if csv is not None:
            return self.request("POST", path, data=csv.encode(), headers={"Content-Type": "text/csv"})
        return self.request("POST", path, {key: list(rows or [])})

    def push_usage(self, fleet_id: str, rows: Iterable[dict] | None = None, *, csv: str | None = None,
                   file: str | None = None) -> dict:
        """Update a fleet's items' current use (and optional rate): rows of
        ``{name (or id), current_use, rate?}``, CSV text or a CSV file."""
        return self._ingest(f"/api/ingest/fleets/{urllib.parse.quote(fleet_id)}/usage", rows, csv, file, "items")

    def push_readings(self, rows: Iterable[dict] | None = None, *, csv: str | None = None,
                      file: str | None = None) -> dict:
        """Readings for Reliafy Maintenance's measurement points: rows of
        ``{tag, value, time?}``, CSV text or a CSV file."""
        return self._ingest("/api/ingest/maintenance/readings", rows, csv, file, "readings")

    def push_measurements(self, fleet_id: str, rows: Iterable[dict] | None = None, *, csv: str | None = None,
                          file: str | None = None) -> dict:
        """Degradation readings ``{item, time, value}`` for a tracked fleet."""
        return self._ingest(f"/api/ingest/tracking/{urllib.parse.quote(fleet_id)}/measurements",
                            rows, csv, file, "measurements")

    def push_lives(self, dataset_id: str, rows: Iterable[dict] | None = None, *, csv: str | None = None,
                   file: str | None = None, refit: bool = True) -> dict:
        """Append life-data rows to a dataset (and refit its models)."""
        path = f"/api/ingest/datasets/{urllib.parse.quote(dataset_id)}/lives" + ("" if refit else "?refit=false")
        return self._ingest(path, rows, csv, file, "rows")

