"""Windows acceptance check - run this ON THE HP.

Everything in the normal test suite is platform-independent by design, but
"portable by construction" is a claim, not a measurement.  This script makes
the measurement: it exercises exactly the things that behave differently on
Windows and prints a verdict per item.

    cd burgys-builds
    python tests\\windows_check.py

It writes only into a temporary directory and starts a server on an ephemeral
loopback port.  It does not build anything, does not touch signing material,
and does not spend money.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS: list = []
ON_WINDOWS = os.name == "nt"


class Skip(Exception):
    """Raised by a check that only means something on Windows."""


def check(name: str):
    def wrap(fn):
        def run():
            try:
                detail = fn()
                RESULTS.append(("PASS", name, detail or ""))
            except Skip as exc:
                RESULTS.append(("SKIP", name, str(exc)))
            except AssertionError as exc:
                RESULTS.append(("FAIL", name, str(exc)))
            except Exception as exc:  # noqa: BLE001 - a crash is a failure
                RESULTS.append(("FAIL", name, f"{type(exc).__name__}: {exc}"))
        run.__name__ = fn.__name__
        return run
    return wrap


TMP = Path(tempfile.mkdtemp(prefix="burgys-wincheck-"))


@check("Plattform ist tatsaechlich Windows")
def _platform():
    if not ON_WINDOWS:
        raise Skip(f"os.name={os.name!r} - dieses Skript gehoert auf den HP. "
                   "Die plattformunabhaengigen Pruefungen laufen trotzdem.")
    return f"{sys.platform}, Python {sys.version.split()[0]}"


@check("Pfade mit Leerzeichen und Umlauten")
def _paths():
    from bb.store import read_json, write_json

    d = TMP / "Ordner mit Leerzeichen" / "Bürgys Grüezi"
    d.mkdir(parents=True, exist_ok=True)
    target = d / "zustand.json"
    write_json(target, {"schlüssel": "wert mit Ümlaut", "n": 1})
    assert read_json(target)["schlüssel"] == "wert mit Ümlaut"
    return str(d)


@check("Sehr langer Pfad (>260 Zeichen)")
def _long_path():
    from bb.store import read_json, write_json

    deep = TMP
    for i in range(12):
        deep = deep / f"verzeichnisebene-{i:02d}-mit-langem-namen"
    deep.mkdir(parents=True, exist_ok=True)
    target = deep / "manifest.json"
    try:
        write_json(target, {"tief": True})
    except OSError as exc:
        raise AssertionError(
            f"Pfadlaenge {len(str(target))} scheitert: {exc}. "
            "Abhilfe: LongPathsEnabled in der Registry, oder Buergys Builds "
            "naeher an C:\\\\ ablegen") from None
    assert read_json(target) == {"tief": True}
    return f"{len(str(target))} Zeichen ok"


@check("Atomares Ersetzen (os.replace)")
def _atomic():
    from bb.store import read_json, write_json

    target = TMP / "atomar.json"
    for i in range(25):
        write_json(target, {"i": i})
    assert read_json(target) == {"i": 24}
    leftovers = list(TMP.glob("atomar.json.*"))
    assert not leftovers, f"temporaere Reste: {leftovers}"
    return "25 Ueberschreibungen, keine Reste"


@check("Ersetzen waehrend die Datei offen ist (AV/Indexer-Fall)")
def _replace_while_open():
    from bb.store import write_json

    target = TMP / "offen.json"
    write_json(target, {"a": 1})
    handle = open(target, "r", encoding="utf-8")
    try:
        write_json(target, {"a": 2})
        outcome = "replace gelingt auch bei offenem Lesehandle"
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"replace scheitert bei offenem Handle: {exc} - der Retry in "
            "bb/store.py muesste greifen") from None
    finally:
        handle.close()
    return outcome


@check("Verzeichnis-Lock ueber mehrere Prozesse")
def _cross_process_lock():
    root = TMP / "locktest"
    root.mkdir(exist_ok=True)
    script = (
        "import sys;"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r});"
        "from bb.config import load_config;"
        "from bb.manifest import BuildNumbers;"
        f"cfg = load_config(env={{'BURGYS_DATA': {str(root)!r}}});"
        "print(BuildNumbers(cfg.paths().ensure()).allocate('wincheck'))"
    )
    procs = [subprocess.Popen([sys.executable, "-c", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for _ in range(8)]
    got = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, f"Prozess scheiterte: {err.decode()[-300:]}"
        got.append(int(out.decode().strip()))
    assert sorted(got) == list(range(1, 9)), f"doppelte Buildnummern: {sorted(got)}"
    return "8 Prozesse, 8 verschiedene Nummern"


@check("Lock ueberlebt Aufraeumen (kein haengendes Verzeichnis)")
def _lock_cleanup():
    from bb.store import FileLock

    path = TMP / ".wincheck.lock"
    for _ in range(5):
        with FileLock(path, timeout=10):
            pass
        assert not path.exists(), "Lock-Verzeichnis blieb liegen"
    return "5 Zyklen sauber"


@check("git laeuft als Argumentliste")
def _git():
    from bb import gitinfo

    repo = TMP / "gitrepo"
    repo.mkdir(exist_ok=True)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x.invalid")
    if not shutil.which("git"):
        raise AssertionError("git ist nicht im PATH")
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"],
                   check=True, env=env, capture_output=True)
    (repo / "datei.txt").write_text("inhalt", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "test"],
                   check=True, env=env, capture_output=True)
    assert gitinfo.is_repo(repo)
    commit = gitinfo.head_commit(repo)
    assert len(commit) == 40
    clean, dirty = gitinfo.is_clean(repo)
    assert clean, f"frisches Repo gilt als schmutzig: {dirty}"
    return f"HEAD {commit[:8]}"


@check("npm/node werden als .cmd gefunden und ausgefuehrt")
def _npm():
    exe = shutil.which("npm")
    if not exe:
        return "npm nicht installiert - Preflight warnt dann nur (kein Fehler)"
    res = subprocess.run([exe, "--version"], capture_output=True, text=True,
                         timeout=120)
    assert res.returncode == 0, f"npm --version scheitert: {res.stderr[:200]}"
    return f"{exe} -> {res.stdout.strip()}"


@check("Token-Datei und Rechte-Meldung")
def _tokens():
    from bb.auth import TokenStore

    store = TokenStore(TMP / "tokens.json")
    store.ensure()
    names = sorted(t["name"] for t in store.tokens())
    assert names == ["agent", "release"], names
    state = store.permissions_state()
    expected = "unchecked" if ON_WINDOWS else "ok"
    assert state == expected, f"Rechtezustand {state!r}, erwartet {expected!r}"
    return f"zwei Tokens, Rechte als {state!r} gemeldet"


@check("Server bindet exklusiv auf 127.0.0.1")
def _server():
    from bb.api import BurgysServer, serve
    from bb.builds import BuildController
    from bb.config import load_config
    from bb.projects import Registry

    from bb.api import reuse_address_default
    assert reuse_address_default("nt") is False, (
        "allow_reuse_address muss unter Windows False sein, sonst kann ein "
        "anderer lokaler Prozess den Port uebernehmen")
    assert BurgysServer.allow_reuse_address is reuse_address_default(os.name)
    cfg = load_config(env={"BURGYS_DATA": str(TMP / "srv"),
                           "BURGYS_API_TOKEN_FILE": str(TMP / "srvtok.json")})
    controller = BuildController(cfg, Registry([]))
    server = serve(controller, "127.0.0.1", 0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as r:
            assert json.loads(r.read().decode())["status"] == "ok"
        # A second bind on the same port must be refused, not silently allowed.
        if ON_WINDOWS:
            # The point of exclusive binding: nobody else may take this port.
            hijack = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                hijack.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    hijack.bind(("127.0.0.1", port))
                    raise AssertionError(
                        "ein zweiter Prozess konnte denselben Port binden - "
                        "Port-Uebernahme moeglich")
                except OSError:
                    pass
            finally:
                hijack.close()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/status")
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("/status ohne Token erreichbar")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401, exc.code
    finally:
        server.shutdown()
        server.server_close()
    return f"Port {port}, exklusiv, /status verlangt Token"


@check("QR-Dateien lassen sich schreiben")
def _qr():
    from bb import qr

    m = qr.encode("https://sebastianbuergy-oss.github.io/band-apps-install/", "M")
    svg = TMP / "qr.svg"
    png = TMP / "qr.png"
    svg.write_text(qr.to_svg(m), encoding="utf-8", newline="\n")
    png.write_bytes(qr.to_png(m))
    assert png.read_bytes().startswith(b"\x89PNG")
    assert svg.read_text(encoding="utf-8").startswith("<svg")
    return f"{svg.stat().st_size} B SVG, {png.stat().st_size} B PNG"


@check("IPA-Inspektion (falls eine IPA daneben liegt)")
def _ipa():
    candidate = Path(__file__).resolve().parents[2] / "thy-gnosis.ipa"
    if not candidate.exists():
        return "keine IPA gefunden - uebersprungen"
    from bb.ipa import distribution_kind, inspect

    info = inspect(candidate)
    assert info["bundle_id"] == "com.sebastianbuergy.thygnosis", info["bundle_id"]
    assert len(info["sha256"]) == 64
    assert distribution_kind(info) == "AD_HOC"
    return f"{info['bundle_id']} {info['version']}({info['build_number']}) sha {info['sha256'][:12]}"


@check("Volle Testsuite laeuft unter Windows")
def _suite():
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "tests"],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=1800)
    tail = res.stderr.strip().splitlines()[-3:]
    assert res.returncode == 0, "Suite rot:\n  " + "\n  ".join(tail)
    ran = next((l for l in tail if l.startswith("Ran ")), "?")
    return ran


def main() -> int:
    checks = [_platform, _paths, _long_path, _atomic, _replace_while_open,
              _cross_process_lock, _lock_cleanup, _git, _npm, _tokens,
              _server, _qr, _ipa, _suite]
    print("Buergys Builds - Windows-Abnahme")
    print("=" * 74)
    for fn in checks:
        fn()
    print()
    for status, name, detail in RESULTS:
        mark = {"PASS": "  ok ", "FAIL": "FAIL", "SKIP": " -- "}[status]
        print(f"{mark}  {name}")
        if detail:
            print(f"        {detail}")
    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = [r for r in RESULTS if r[0] == "SKIP"]
    passed = len(RESULTS) - len(failed) - len(skipped)
    print("=" * 74)
    print(f"{passed} bestanden, {len(failed)} fehlgeschlagen, {len(skipped)} uebersprungen")
    shutil.rmtree(TMP, ignore_errors=True)
    if failed:
        print("\nBITTE DIESE AUSGABE AN CLAUDE/CODEX ZURUECKGEBEN.")
        return 1
    if not ON_WINDOWS:
        print("\nNicht auf Windows gelaufen - das ist KEINE Windows-Abnahme.")
        return 0
    print("\nWindows-Abnahme bestanden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
