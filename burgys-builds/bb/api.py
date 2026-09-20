"""The local Agent API and the dashboard (master brief, sections 12 and 19).

Bound to 127.0.0.1 by design: Buergys Builds holds signing decisions and
build triggers, and nothing about it wants to be reachable from the
network.  Every route is authenticated, rate limited and validates its own
input; no route ever takes a filesystem path from the caller.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import auth as AU
from . import dashboard as DASH
from . import states as S
from .audit import API_DENIED
from .builds import BuildController
from .errors import BurgysError, ValidationError
from .executors import get_executor
from .ids import validate_build_id, validate_project_id
from .ratelimit import RateLimiter
from .redact import redact
from .store import disk_status

MAX_BODY = 64 * 1024
SESSION_TTL = 8 * 3600


class _Sessions:
    """Short-lived dashboard cookies, exchanged for a token once."""

    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = threading.Lock()

    def create(self, name: str) -> str:
        sid = secrets.token_urlsafe(24)
        with self._lock:
            self._data[sid] = (time.time() + SESSION_TTL, name)
        return sid

    def valid(self, sid: str | None) -> str | None:
        if not sid:
            return None
        with self._lock:
            entry = self._data.get(sid)
            if not entry:
                return None
            if entry[0] < time.time():
                self._data.pop(sid, None)
                return None
            return entry[1]


class BurgysServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, controller: BuildController) -> None:
        super().__init__(address, BurgysHandler)
        self.controller = controller
        self.tokens = AU.TokenStore(controller.config["api_token_file"])
        self.limiter = RateLimiter(controller.config.get("api_rate_limit_per_minute", 120))
        self.sessions = _Sessions()
        self.started_at = time.time()


_ROUTES: list = []


def route(method: str, pattern: str, scope: str):
    compiled = re.compile("^" + pattern + "$")

    def wrap(fn):
        _ROUTES.append((method, compiled, scope, fn))
        return fn

    return wrap


class BurgysHandler(BaseHTTPRequestHandler):
    server_version = "BurgysBuilds"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing -------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        return  # the audit log is the record; access spam is not

    @property
    def controller(self) -> BuildController:
        return self.server.controller

    def _send(self, status: int, payload, *, content_type="application/json; charset=utf-8",
              extra_headers: dict | None = None) -> None:
        if isinstance(payload, (dict, list)):
            body = json.dumps(redact(payload), ensure_ascii=False, indent=2).encode("utf-8")
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = payload or b""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
            "script-src 'unsafe-inline'; form-action 'none'; frame-ancestors 'none'")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send(status, {"error": message, "status": status})

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValidationError("Content-Length ist keine Zahl")
        if length > MAX_BODY:
            raise ValidationError(f"Request Body groesser als {MAX_BODY} Bytes")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValidationError(f"Body ist kein gueltiges JSON: {exc}") from None
        if not isinstance(data, dict):
            raise ValidationError("Body muss ein JSON-Objekt sein")
        return data

    def _presented_token(self) -> str | None:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return self.headers.get("X-Burgys-Token") or None

    def _cookie(self, name: str) -> str | None:
        for part in (self.headers.get("Cookie") or "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    # -- dispatch -------------------------------------------------------
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_HEAD(self) -> None:
        self._dispatch("GET")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        client = self.client_address[0] if self.client_address else "?"
        if client not in ("127.0.0.1", "::1"):
            # Belt and braces: the socket is already bound to localhost.
            return self._error(HTTPStatus.FORBIDDEN, "nur lokal erreichbar")

        allowed, retry = self.server.limiter.check(client)
        if not allowed:
            return self._send(HTTPStatus.TOO_MANY_REQUESTS,
                              {"error": "zu viele Anfragen", "retry_after": retry},
                              extra_headers={"Retry-After": str(retry)})

        if path == "/health":
            return self._send(HTTPStatus.OK, {"status": "ok", "service": "burgys-builds"})
        if path in ("/", "/dashboard"):
            return self._dashboard(query)

        for verb, pattern, scope, handler in _ROUTES:
            match = pattern.match(path)
            if not match or verb != method:
                continue
            identity = self._authorize(scope, path)
            if identity is None:
                return
            try:
                status, payload = handler(self, identity, match.groupdict(), query)
            except ValidationError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except BurgysError as exc:
                return self._send(HTTPStatus.CONFLICT,
                                  {"error": str(exc), "state": getattr(exc, "state", None)})
            except Exception as exc:  # never leak a traceback to a caller
                self.controller.audit.record(API_DENIED, actor="api", result="error",
                                             detail=f"{type(exc).__name__}")
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                                   f"interner Fehler ({type(exc).__name__})")
            return self._send(status, payload)
        return self._error(HTTPStatus.NOT_FOUND, f"keine Route fuer {method} {path}")

    def _authorize(self, scope: str, path: str) -> dict | None:
        entry = self.server.tokens.allows(self._presented_token(), scope)
        if entry:
            return entry
        session = self.server.sessions.valid(self._cookie("burgys_session"))
        if session and scope in (AU.SCOPES.get(session) or []):
            return {"name": session, "scopes": AU.SCOPES[session]}
        self.controller.audit.record(
            API_DENIED, actor="api", result="denied",
            detail={"path": path, "required_scope": scope})
        self._send(HTTPStatus.UNAUTHORIZED,
                   {"error": f"Token mit Scope '{scope}' noetig", "scope": scope},
                   extra_headers={"WWW-Authenticate": 'Bearer realm="burgys-builds"'})
        return None

    # -- dashboard ------------------------------------------------------
    def _dashboard(self, query: dict) -> None:
        token = (query.get("token") or [None])[0]
        headers = {}
        name = self.server.sessions.valid(self._cookie("burgys_session"))
        if token:
            entry = self.server.tokens.identify(token)
            if not entry:
                return self._error(HTTPStatus.UNAUTHORIZED, "unbekanntes Token")
            sid = self.server.sessions.create(entry["name"])
            name = entry["name"]
            headers["Set-Cookie"] = (
                f"burgys_session={sid}; Path=/; HttpOnly; SameSite=Strict; "
                f"Max-Age={SESSION_TTL}")
        if not name:
            return self._send(
                HTTPStatus.UNAUTHORIZED,
                DASH.render_login(),
                content_type="text/html; charset=utf-8")
        html = DASH.render(self.controller, system_status(self.controller), name)
        return self._send(HTTPStatus.OK, html,
                          content_type="text/html; charset=utf-8",
                          extra_headers=headers)


# --------------------------------------------------------------------------
# system status
# --------------------------------------------------------------------------

def system_status(controller: BuildController) -> dict:
    executors = {}
    for project in controller.registry.all():
        try:
            ex = controller.executor_for(project)
            executors[project.id] = ex.describe()
        except Exception as exc:
            executors[project.id] = {"name": "?", "availability": "OFFLINE",
                                     "error": str(exc)[:200]}
    default_name = controller.config.get("default_executor") or "none"
    try:
        default = get_executor(default_name).describe()
    except Exception:
        default = {"name": default_name, "availability": "OFFLINE"}
    today = [m for m in controller.list_builds(limit=200)
             if (m.get("created_at") or "")[:10] == __import__("datetime").date.today().isoformat()]
    return {
        "windows_controller": "ONLINE",
        "mac_executor": default,
        "mac_executors_per_project": executors,
        "cost_guard": controller.cost_guard.status(),
        "queue": controller.queue.snapshot(),
        "builds_today": {
            "total": len(today),
            "success": sum(1 for m in today if m.status == S.SUCCESS),
            "failed": sum(1 for m in today if m.status in (S.FAILED, S.BLOCKED,
                                                           S.BLOCKED_BY_COST_GUARD)),
            "dry_runs": sum(1 for m in today if m.is_dry_run),
        },
        "disk": disk_status(controller.paths.root,
                            int(controller.config["min_free_bytes"]),
                            int(controller.config["warn_free_bytes"])),
    }


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

@route("GET", "/status", AU.READ)
def _status(h, identity, params, query):
    return HTTPStatus.OK, system_status(h.controller)


@route("GET", "/queue", AU.READ)
def _queue(h, identity, params, query):
    return HTTPStatus.OK, h.controller.queue.snapshot()


@route("GET", "/projects", AU.READ)
def _projects(h, identity, params, query):
    return HTTPStatus.OK, [p.to_dict() for p in h.controller.registry.all()]


@route("GET", r"/projects/(?P<project_id>[a-z0-9-]{1,50})", AU.READ)
def _project(h, identity, params, query):
    project = h.controller.registry.get(validate_project_id(params["project_id"]))
    builds = h.controller.list_builds(project.id, limit=20)
    return HTTPStatus.OK, {
        "project": project.to_dict(),
        "limit": h.controller.limiter.status(project.id),
        "builds": [m.to_dict() for m in builds],
    }


@route("POST", "/preflight", AU.PREFLIGHT)
def _preflight(h, identity, params, query):
    body = h._body()
    project_id = validate_project_id(str(body.get("project", "")))
    mode = str(body.get("mode") or "AD_HOC")
    report = h.controller.preflight(project_id, mode,
                                    commit=body.get("commit"),
                                    actor=identity["name"])
    return HTTPStatus.OK, report.to_dict()


@route("POST", "/builds", AU.PREPARE)
def _create_build(h, identity, params, query):
    body = h._body()
    project_id = validate_project_id(str(body.get("project", "")))
    mode = str(body.get("mode") or "AD_HOC")
    dry_run = bool(body.get("dry_run", False))
    # Preparing is free; starting a real macOS job is not.  An agent token
    # may do the first and not the second.
    if not dry_run and AU.BUILD not in (identity.get("scopes") or []):
        h.controller.audit.record(
            API_DENIED, actor=identity["name"], project=project_id, result="denied",
            detail="echter Build braucht Scope 'build'")
        raise ValidationError(
            "Ein echter Build braucht das Release-Token (Scope 'build'). "
            "Mit dry_run=true laeuft die Pipeline kostenlos durch.")
    manifest = h.controller.request_build(
        project_id, mode, requested_by=identity["name"],
        commit=body.get("commit"), dry_run=dry_run)
    return HTTPStatus.ACCEPTED, manifest.to_dict()


@route("GET", r"/builds/(?P<build_id>BB-\d{8}-[A-Z0-9]{2,6}-\d{3,})", AU.READ)
def _build(h, identity, params, query):
    return HTTPStatus.OK, h.controller.get(validate_build_id(params["build_id"])).to_dict()


@route("POST", r"/builds/(?P<build_id>BB-\d{8}-[A-Z0-9]{2,6}-\d{3,})/cancel", AU.PREPARE)
def _cancel(h, identity, params, query):
    manifest = h.controller.cancel(validate_build_id(params["build_id"]),
                                   actor=identity["name"])
    return HTTPStatus.OK, manifest.to_dict()


@route("POST", r"/builds/(?P<build_id>BB-\d{8}-[A-Z0-9]{2,6}-\d{3,})/approve", AU.RELEASE)
def _approve(h, identity, params, query):
    manifest = h.controller.approve(validate_build_id(params["build_id"]),
                                    approved_by=identity["name"])
    return HTTPStatus.OK, manifest.to_dict()


@route("GET", r"/builds/(?P<build_id>BB-\d{8}-[A-Z0-9]{2,6}-\d{3,})/logs", AU.READ)
def _logs(h, identity, params, query):
    build_id = validate_build_id(params["build_id"])
    try:
        tail = min(5000, max(1, int((query.get("tail") or ["500"])[0])))
    except ValueError:
        raise ValidationError("tail muss eine Zahl sein")
    return HTTPStatus.OK, {"build_id": build_id, "lines": h.controller.logs(build_id, tail)}


@route("GET", r"/builds/(?P<build_id>BB-\d{8}-[A-Z0-9]{2,6}-\d{3,})/artifacts", AU.READ)
def _artifacts(h, identity, params, query):
    build_id = validate_build_id(params["build_id"])
    manifest = h.controller.get(build_id)
    directory = h.controller.paths.artifact_dir(build_id)
    files = []
    if directory.exists():
        for item in sorted(directory.iterdir()):
            if item.is_file():
                files.append({"name": item.name, "bytes": item.stat().st_size})
    return HTTPStatus.OK, {
        "build_id": build_id,
        "dry_run": manifest.is_dry_run,
        "artifact_sha256": manifest.get("artifact_sha256"),
        "artifact_bytes": manifest.get("artifact_bytes"),
        "ota": manifest.get("ota"),
        # Names only.  The API never serves file content and never takes a
        # path from the caller.
        "files": files,
    }


@route("GET", "/audit", AU.READ)
def _audit(h, identity, params, query):
    try:
        limit = min(1000, max(1, int((query.get("limit") or ["100"])[0])))
    except ValueError:
        raise ValidationError("limit muss eine Zahl sein")
    project = (query.get("project") or [None])[0]
    if project:
        validate_project_id(project)
    return HTTPStatus.OK, {"entries": h.controller.audit.read(limit, project=project)}


# --------------------------------------------------------------------------

def serve(controller: BuildController, host: str | None = None,
          port: int | None = None) -> BurgysServer:
    host = host or controller.config["api_host"]
    port = int(port if port is not None else controller.config["api_port"])
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValidationError(
            f"api_host={host!r} abgelehnt. Buergys Builds bindet nur lokal; "
            "fuer Fernzugriff einen SSH-Tunnel verwenden (docs/AGENT_API.md).")
    server = BurgysServer((host, port), controller)
    server.tokens.ensure()
    controller.queue.recover(controller.audit)
    return server
