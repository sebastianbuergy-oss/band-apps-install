"""``burgys`` - the command line for the HP.

Run it as ``python -m bb.cli <command>``, or through the ``burgys.cmd`` /
``burgys`` wrappers in ``bin/``.
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__
from . import states as S
from .auth import TokenStore
from .builds import BuildController
from .config import DEFAULT_PROJECTS_FILE, load_config
from .errors import BurgysError
from .projects import MODE_AD_HOC, MODES, Registry


def _controller(args) -> BuildController:
    config = load_config(args.config)
    if args.executor:
        config["default_executor"] = args.executor
    registry = Registry.load(args.projects or DEFAULT_PROJECTS_FILE)
    return BuildController(config, registry)


def _print(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------

def cmd_init(args) -> int:
    controller = _controller(args)
    store = TokenStore(controller.config["api_token_file"])
    created = not Path(store.path).expanduser().exists()
    store.ensure()
    print(f"Datenverzeichnis : {controller.paths.root}")
    print(f"Tokendatei       : {store.path} {'(neu angelegt)' if created else '(vorhanden)'}")
    if not store.permissions_ok():
        print("  WARNUNG: die Tokendatei ist nicht nur fuer den Besitzer lesbar.")
    print(f"Projekte         : {len(controller.registry)} konfiguriert")
    print(f"Cost Guard       : PAID_SERVICES_ALLOWED="
          f"{str(controller.cost_guard.allowed).lower()}")
    print(f"Executor         : {controller.config['default_executor']}")
    for entry in store.tokens():
        print(f"  Token {entry['name']:<8} Scopes: {', '.join(entry['scopes'])}")
    print("\nDie Tokens selbst stehen in der Datei oben und werden hier "
          "absichtlich nicht ausgegeben.")
    return 0


def cmd_projects(args) -> int:
    controller = _controller(args)
    for project in controller.registry.all(include_disabled=True):
        limit = controller.limiter.status(project.id)
        print(f"{project.id:<16} {project.code:<4} {project.bundle_id:<36} "
              f"{project.migration_state:<22} Limit {limit['remaining']}/{limit['limit']}"
              + ("" if project.local_path else "   [kein local_path konfiguriert]"))
    return 0


def cmd_preflight(args) -> int:
    controller = _controller(args)
    report = controller.preflight(args.project, args.mode, commit=args.commit,
                                  actor=args.actor)
    if args.json:
        _print(report.to_dict())
    else:
        for result in report.results:
            mark = {"PASS": "  ok ", "FAIL": " FAIL", "WARN": " warn", "SKIP": " --- "}[result.status]
            print(f"{mark}  {result.name:<28} {result.message}")
            if result.status in ("FAIL", "WARN") and isinstance(result.detail, dict):
                for key, value in result.detail.items():
                    if value and key != "output":
                        print(f"          {key}: {str(value)[:300]}")
        summary = report.to_dict()["summary"]
        print(f"\n{summary['pass']} ok, {summary['fail']} Fehler, "
              f"{summary['warn']} Warnungen, {summary['skip']} uebersprungen")
    return 0 if report.ok else 1


def cmd_build(args) -> int:
    controller = _controller(args)
    manifest = controller.request_build(
        args.project, args.mode, requested_by=args.actor, commit=args.commit,
        dry_run=args.dry_run, approved_by=args.approved_by)
    print(f"{manifest.build_id}  {manifest.display_status()}")
    if manifest.status == S.WAITING_APPROVAL:
        print(f"  Freigabe noetig: burgys approve {manifest.build_id}")
    if manifest.get("failure_reason"):
        print(f"  Grund: {manifest.get('failure_reason')}")
    if manifest.status == S.QUEUED and args.run:
        done = controller.run_next(poll_interval=args.poll)
        if done is not None:
            print(f"{done.build_id}  {done.display_status()}")
            if done.get("failure_reason"):
                print(f"  Grund: {done.get('failure_reason')}")
            return 0 if done.status == S.SUCCESS else 1
    return 0


def cmd_run(args) -> int:
    controller = _controller(args)
    manifest = controller.run_next(poll_interval=args.poll)
    if manifest is None:
        print("Queue ist leer.")
        return 0
    print(f"{manifest.build_id}  {manifest.display_status()}")
    if manifest.get("failure_reason"):
        print(f"  Grund: {manifest.get('failure_reason')}")
    return 0 if manifest.status == S.SUCCESS else 1


def cmd_approve(args) -> int:
    controller = _controller(args)
    manifest = controller.approve(args.build_id, approved_by=args.actor)
    print(f"{manifest.build_id}  {manifest.status}  (freigegeben von {args.actor})")
    return 0


def cmd_cancel(args) -> int:
    controller = _controller(args)
    manifest = controller.cancel(args.build_id, actor=args.actor)
    print(f"{manifest.build_id}  {manifest.status}")
    return 0


def cmd_builds(args) -> int:
    controller = _controller(args)
    for manifest in controller.list_builds(args.project, limit=args.limit):
        print(f"{manifest.build_id}  {manifest.get('project'):<14} "
              f"{(manifest.get('commit') or '')[:8]:<9} "
              f"{manifest.get('mode'):<18} {manifest.display_status()}")
    return 0


def cmd_logs(args) -> int:
    controller = _controller(args)
    lines = controller.logs(args.build_id, args.tail)
    print("\n".join(lines) if lines else "(kein Log)")
    return 0


def cmd_status(args) -> int:
    from .api import system_status

    _print(system_status(_controller(args)))
    return 0


def cmd_recover(args) -> int:
    controller = _controller(args)
    _print(controller.queue.recover(controller.audit))
    return 0


def cmd_ipa(args) -> int:
    from .ipa import distribution_kind, inspect

    info = inspect(args.path)
    info["distribution"] = distribution_kind(info)
    _print(info)
    return 0


def cmd_ota(args) -> int:
    controller = _controller(args)
    manifest = controller.get(args.build_id)
    release = manifest.get("ota")
    if not release:
        print(f"{args.build_id}: keine OTA-Veroeffentlichung "
              f"(Status {manifest.display_status()})")
        return 1
    _print(release)
    return 0


def cmd_qr(args) -> int:
    from . import qr

    matrix = qr.encode(args.text, args.level)
    if args.out:
        out = Path(args.out)
        if out.suffix.lower() == ".png":
            out.write_bytes(qr.to_png(matrix))
        else:
            out.write_text(qr.to_svg(matrix), encoding="utf-8", newline="\n")
        print(f"{out}  ({len(matrix)}x{len(matrix)} Module)")
    else:
        print(qr.to_text(matrix))
    return 0


def cmd_serve(args) -> int:
    from .api import serve

    controller = _controller(args)
    server = serve(controller, args.host, args.port)
    host, port = server.server_address[0], server.server_address[1]
    print(f"Buergys Builds auf http://{host}:{port}/  (nur lokal)")
    print("Beenden mit Strg+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nangehalten")
    finally:
        server.server_close()
    return 0


def cmd_dashboard(args) -> int:
    from .api import serve

    controller = _controller(args)
    server = serve(controller, args.host, args.port)
    host, port = server.server_address[0], server.server_address[1]
    token = next(e["token"] for e in server.tokens.tokens() if e["name"] == "agent")
    url = f"http://{host}:{port}/?token={token}"
    print(f"Dashboard: {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nangehalten")
    finally:
        server.server_close()
    return 0


def cmd_doctor(args) -> int:
    from .doctor import report

    text = report()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        print(f"geschrieben: {args.out}")
    else:
        print(text)
    return 0


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="burgys", description="Buergys Builds - Windows-first iOS Build Controller")
    parser.add_argument("--version", action="version", version=f"burgys {__version__}")
    parser.add_argument("--config", help="Pfad zu burgys.json")
    parser.add_argument("--projects", help="Pfad zu projects.json")
    parser.add_argument("--executor", help="Executor ueberschreiben (none, dryrun, github, local)")
    parser.add_argument("--actor", default="sebastian", help="wer handelt (fuer das Audit-Log)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Datenverzeichnis und Tokens anlegen").set_defaults(fn=cmd_init)
    sub.add_parser("projects", help="konfigurierte Projekte auflisten").set_defaults(fn=cmd_projects)
    sub.add_parser("status", help="Systemstatus als JSON").set_defaults(fn=cmd_status)
    sub.add_parser("recover", help="Queue nach einem Neustart aufraeumen").set_defaults(fn=cmd_recover)

    p = sub.add_parser("preflight", help="Windows-Preflight fuer ein Projekt")
    p.add_argument("project")
    p.add_argument("--mode", default=MODE_AD_HOC, choices=MODES)
    p.add_argument("--commit")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_preflight)

    p = sub.add_parser("build", help="Build anfordern")
    p.add_argument("project")
    p.add_argument("--mode", default=MODE_AD_HOC, choices=MODES)
    p.add_argument("--commit")
    p.add_argument("--dry-run", action="store_true",
                   help="Pipeline ohne Mac durchlaufen; zaehlt nicht als Build")
    p.add_argument("--approved-by", help="Freigabe direkt mitgeben")
    p.add_argument("--run", action="store_true", help="direkt ausfuehren, nicht nur einreihen")
    p.add_argument("--poll", type=float, default=5.0)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("run", help="naechsten Build aus der Queue ausfuehren")
    p.add_argument("--poll", type=float, default=5.0)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("approve", help="wartenden Build freigeben")
    p.add_argument("build_id")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("cancel", help="Build abbrechen")
    p.add_argument("build_id")
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("builds", help="Builds auflisten")
    p.add_argument("--project")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_builds)

    p = sub.add_parser("logs", help="Log eines Builds")
    p.add_argument("build_id")
    p.add_argument("--tail", type=int, default=500)
    p.set_defaults(fn=cmd_logs)

    p = sub.add_parser("ota", help="OTA-Daten eines Builds")
    p.add_argument("build_id")
    p.set_defaults(fn=cmd_ota)

    p = sub.add_parser("ipa", help="eine IPA untersuchen (ohne Mac)")
    p.add_argument("path")
    p.set_defaults(fn=cmd_ipa)

    p = sub.add_parser("qr", help="QR-Code erzeugen")
    p.add_argument("text")
    p.add_argument("--level", default="M", choices=["L", "M", "Q", "H"])
    p.add_argument("--out", help="Datei (.svg oder .png); ohne Angabe im Terminal")
    p.set_defaults(fn=cmd_qr)

    p = sub.add_parser("serve", help="API und Dashboard starten")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("dashboard", help="Dashboard starten und oeffnen")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_dashboard)

    p = sub.add_parser("doctor", help="Rechner und Werkzeuge untersuchen")
    p.add_argument("--out", help="Bericht in eine Datei schreiben")
    p.set_defaults(fn=cmd_doctor)
    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except BurgysError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
