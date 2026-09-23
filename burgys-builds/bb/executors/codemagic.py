"""Codemagic macOS executor.

Sebastian baut seine Apps seit Monaten bei Codemagic, von Hand im Browser. Der
Executor macht daraus einen Schritt in der Kette: Buergys prueft auf Windows
vorab, und nur was durchkommt, loest hier einen Build aus.

Kosten, ehrlich: Codemagic ist **nicht** gratis. Am 23.09.2026 standen in
Sebastians Konto 505 von 500 Gratis-Minuten und ein offener Saldo von 53.68
USD; die Rechnung des Vormonats war 84.08 USD. Der Executor meldet darum jede
verbrauchte Minute an die Kostenbremse zurueck, damit niemand wieder erst auf
der Rechnung merkt, dass der Gratis-Anteil weg ist.

Das Token liegt in einer Datei ausserhalb des Repositories und wird nie
geloggt. Wie beim GitHub-Executor loest hier nichts ohne Konfiguration aus.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..errors import ConfigError, ExecutorUnavailable, ValidationError
from ..redact import redact_text
from . import AVAILABLE, BUSY, OFFLINE, MacExecutor, MacJob, MacJobResult, register

API = "https://api.codemagic.io"

#: Eine fertige .ipa dieser Apps liegt bei 25 bis 60 MB. Die Grenze ist grosszuegig,
#: aber endlich: Ein Download darf Sebastians Platte nicht vollschreiben.
MAX_ARTEFAKT_BYTES = 512 * 1024 * 1024

ID_RE = re.compile(r"^[A-Za-z0-9]{12,40}$")

#: Codemagic kennt mehr Zustaende als wir. Alles, was nicht hier steht, gilt als laufend.
FERTIG = {"finished": "SUCCESS", "failed": "FAILED", "canceled": "CANCELLED",
          "cancelled": "CANCELLED", "timeout": "FAILED", "skipped": "CANCELLED"}


@register
class CodemagicExecutor(MacExecutor):
    name = "codemagic"
    cost_resource = "codemagic"
    produces_real_ipa = True

    def __init__(self, config=None) -> None:
        super().__init__(config)
        self.app_id = self.config.get("app_id") or ""
        self.workflow_id = self.config.get("workflow_id") or ""
        self.branch = self.config.get("branch") or "main"
        self.token_file = self.config.get("token_file") or ""
        self.api_base = (self.config.get("api_base") or API).rstrip("/")
        #: Wird beim ersten Blick auf die App gefuellt (z. B. "mac_mini_m2").
        self._instance = self.config.get("instance_type") or ""
        self._handles: dict[str, dict] = {}

    # -- Zugang --------------------------------------------------------
    def _token(self) -> str:
        if not self.token_file:
            raise ConfigError(
                "CodemagicExecutor: token_file ist nicht konfiguriert. "
                "Das Token gehoert nie ins Repository."
            )
        pfad = Path(self.token_file).expanduser()
        if not pfad.exists():
            raise ConfigError(f"CodemagicExecutor: Tokendatei fehlt: {pfad}")
        token = pfad.read_text(encoding="utf-8").strip()
        if not token:
            raise ConfigError(f"CodemagicExecutor: Tokendatei {pfad} ist leer")
        return token

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        daten = json.dumps(body).encode() if body is not None else None
        anfrage = urllib.request.Request(
            self.api_base + path, data=daten, method=method,
            headers={
                "x-auth-token": self._token(),
                "Accept": "application/json",
                "User-Agent": "burgys-builds",
                **({"Content-Type": "application/json"} if daten else {}),
            },
        )
        try:
            with urllib.request.urlopen(anfrage, timeout=30) as antwort:
                roh = antwort.read().decode("utf-8") or "{}"
                return json.loads(roh) if roh.strip() else {}
        except urllib.error.HTTPError as fehler:
            text = redact_text(fehler.read().decode("utf-8", "replace")[:500])
            raise ExecutorUnavailable(
                f"Codemagic API {method} {path} -> {fehler.code}: {text}"
            ) from None
        except urllib.error.URLError as fehler:
            raise ExecutorUnavailable(f"Codemagic nicht erreichbar: {fehler.reason}") from None

    @property
    def runner_label(self) -> str:  # type: ignore[override]
        return self._instance

    def configured(self) -> bool:
        return bool(self.app_id and self.workflow_id and self.token_file
                    and Path(self.token_file).expanduser().exists())

    # -- Schnittstelle -------------------------------------------------
    def availability(self) -> str:
        if not self.configured():
            return OFFLINE
        try:
            antwort = self._request("GET", f"/builds?appId={urllib.parse.quote(self.app_id)}&limit=5")
        except Exception:
            return OFFLINE
        laufend = [b for b in antwort.get("builds", [])
                   if str(b.get("status", "")).lower() not in FERTIG]
        return BUSY if laufend else AVAILABLE

    def submit(self, job: MacJob) -> str:
        if not self.configured():
            raise ExecutorUnavailable(
                "CodemagicExecutor: app_id, workflow_id oder token_file fehlen."
            )
        for wert, feld in ((self.app_id, "app_id"), (self.workflow_id, "workflow_id")):
            if not ID_RE.match(wert):
                raise ValidationError(f"CodemagicExecutor: {feld} {wert!r} sieht nicht wie eine Kennung aus")
        antwort = self._request("POST", "/builds", {
            "appId": self.app_id,
            "workflowId": self.workflow_id,
            "branch": job.branch or self.branch,
        })
        handle = str(antwort.get("buildId") or "")
        if not handle:
            raise ExecutorUnavailable(f"Codemagic hat keine Build-Kennung geliefert: {antwort}")
        self._handles[handle] = {"job": job.build_id}
        return handle

    @staticmethod
    def _minuten(build: dict) -> float:
        """Verbrauchte Mac-Minuten aus Start und Ende. Genau das, was Codemagic verrechnet."""
        def zeit(wert):
            if not wert:
                return None
            try:
                return _dt.datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
            except ValueError:
                return None
        start, ende = zeit(build.get("startedAt")), zeit(build.get("finishedAt"))
        if not start:
            return 0.0
        if not ende:
            ende = _dt.datetime.now(_dt.timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=_dt.timezone.utc)
        if ende.tzinfo is None:
            ende = ende.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (ende - start).total_seconds() / 60.0)

    def _build(self, handle: str) -> dict:
        antwort = self._request("GET", f"/builds/{urllib.parse.quote(handle)}")
        return antwort.get("build") or {}

    def poll(self, handle: str) -> MacJobResult:
        build = self._build(handle)
        if not build:
            return MacJobResult(state="MAC_BUILDING", detail="Build noch nicht sichtbar")
        zustand = str(build.get("status", "")).lower()
        minuten = self._minuten(build)
        self._instance = build.get("instanceType") or self._instance
        if zustand not in FERTIG:
            return MacJobResult(state="MAC_BUILDING", detail=f"Codemagic: {zustand}",
                                minutes=minuten)
        return MacJobResult(state=FERTIG[zustand], detail=f"Codemagic: {zustand}",
                            minutes=minuten,
                            raw={"buildId": handle, "index": build.get("index"),
                                 "instanceType": build.get("instanceType")})

    def cancel(self, handle: str) -> bool:
        try:
            self._request("POST", f"/builds/{urllib.parse.quote(handle)}/cancel")
            return True
        except ExecutorUnavailable:
            return False

    # -- Artefakt ------------------------------------------------------
    def fetch_artifact(self, handle: str, dest_dir) -> str | None:
        """Die fertige .ipa herunterladen. Alles andere (Logs, Bundles) bleibt dort."""
        build = self._build(handle)
        ipas = [a for a in (build.get("artefacts") or [])
                if str(a.get("type", "")).lower() == "ipa" or str(a.get("name", "")).endswith(".ipa")]
        if not ipas:
            return None
        artefakt = max(ipas, key=lambda a: int(a.get("size") or 0))
        url = str(artefakt.get("url") or "")
        if not url.startswith("https://"):
            raise ValidationError("CodemagicExecutor: Artefakt-Adresse ist nicht https")
        groesse = int(artefakt.get("size") or 0)
        if groesse > MAX_ARTEFAKT_BYTES:
            raise ExecutorUnavailable(
                f"Artefakt ist {groesse // (1024 * 1024)} MB gross, Grenze sind "
                f"{MAX_ARTEFAKT_BYTES // (1024 * 1024)} MB"
            )
        # Der Name kommt vom Anbieter: nur der letzte Teil, und nur harmlose Zeichen.
        name = Path(str(artefakt.get("name") or "build.ipa")).name
        name = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "build.ipa"
        if not name.endswith(".ipa"):
            name += ".ipa"
        ziel = Path(dest_dir)
        ziel.mkdir(parents=True, exist_ok=True)
        datei = ziel / name
        anfrage = urllib.request.Request(
            url, headers={"x-auth-token": self._token(), "User-Agent": "burgys-builds"})
        gelesen = 0
        try:
            with urllib.request.urlopen(anfrage, timeout=300) as antwort, datei.open("wb") as aus:
                while True:
                    stueck = antwort.read(1024 * 256)
                    if not stueck:
                        break
                    gelesen += len(stueck)
                    if gelesen > MAX_ARTEFAKT_BYTES:
                        raise ExecutorUnavailable("Artefakt ueberschreitet die Groessengrenze")
                    aus.write(stueck)
        except urllib.error.URLError as fehler:
            datei.unlink(missing_ok=True)
            raise ExecutorUnavailable(f"Artefakt nicht ladbar: {fehler.reason}") from None
        except Exception:
            datei.unlink(missing_ok=True)
            raise
        return str(datei)
