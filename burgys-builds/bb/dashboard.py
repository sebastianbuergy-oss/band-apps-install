"""The Buergys Builds dashboard (master brief, section 12).

Server-rendered HTML with no JavaScript and no external assets: it has to
work on the HP with the network off, and a dashboard that can only render
when a CDN answers is not a dashboard for a build system.

Deep navy ground, neon orange for action, electric cyan for live state.
"""
from __future__ import annotations

import html
from typing import Any

from . import states as S

CSS = """
:root{
  --navy-900:#060b18; --navy-800:#0b1327; --navy-700:#111d38; --navy-600:#1b2b4d;
  --line:#22355c; --text:#e8eefc; --muted:#8fa2c7;
  --orange:#ff7a1a; --cyan:#22d3ee; --green:#34d399; --red:#fb7185; --amber:#fbbf24;
}
*{box-sizing:border-box}
body{margin:0;background:var(--navy-900);color:var(--text);
  font:14px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--cyan)}
.wrap{max-width:1140px;margin:0 auto;padding:28px 20px 60px}
header.top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid var(--line);padding-bottom:16px;margin-bottom:26px}
h1{font-size:21px;margin:0;letter-spacing:.14em;text-transform:uppercase}
h1 b{color:var(--orange);font-weight:800}
.tag{color:var(--muted);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
h2{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);
  margin:34px 0 12px;font-weight:600}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(196px,1fr))}
.card{background:var(--navy-800);border:1px solid var(--line);
  border-radius:10px;padding:14px 16px}
.card .k{color:var(--muted);font-size:11px;letter-spacing:.12em;text-transform:uppercase}
.card .v{font-size:22px;font-weight:700;margin-top:4px;letter-spacing:-.01em}
.card .s{color:var(--muted);font-size:12px;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px;
  background:var(--navy-800);border:1px solid var(--line);border-radius:10px;
  overflow:hidden}
th{text-align:left;color:var(--muted);font-size:11px;letter-spacing:.12em;
  text-transform:uppercase;font-weight:600;padding:10px 12px;
  border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid rgba(34,53,92,.5);vertical-align:top}
tr:last-child td{border-bottom:none}
code{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--cyan)}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;
  font-weight:700;letter-spacing:.07em;text-transform:uppercase;white-space:nowrap}
.ok{background:rgba(52,211,153,.14);color:var(--green)}
.live{background:rgba(34,211,238,.14);color:var(--cyan)}
.warn{background:rgba(251,191,36,.14);color:var(--amber)}
.bad{background:rgba(251,113,133,.14);color:var(--red)}
.idle{background:rgba(143,162,199,.14);color:var(--muted)}
.hot{background:rgba(255,122,26,.16);color:var(--orange)}
.banner{border:1px solid var(--line);border-left:3px solid var(--orange);
  background:var(--navy-700);border-radius:8px;padding:12px 16px;margin:0 0 22px;
  color:var(--text);font-size:13px}
.banner b{color:var(--orange)}
.muted{color:var(--muted)}
footer{margin-top:40px;color:var(--muted);font-size:12px;
  border-top:1px solid var(--line);padding-top:14px}
.actions{font-size:12px;color:var(--muted)}
.actions code{color:var(--orange)}
"""

_PILL = {
    S.SUCCESS: "ok", S.READY: "ok",
    S.FAILED: "bad", S.BLOCKED: "bad", S.BLOCKED_BY_COST_GUARD: "bad",
    S.CANCELLED: "idle", S.DISCOVERED: "idle",
    S.WAITING_APPROVAL: "warn", S.QUEUED: "warn", S.WAITING_MAC: "warn",
}


def _pill_class(state: str) -> str:
    if state in _PILL:
        return _PILL[state]
    return "live"  # PREFLIGHT, WINDOWS_TESTING, MAC_BUILDING, SIGNING, ...


def _pill(text: str, cls: str) -> str:
    return f'<span class="pill {cls}">{html.escape(str(text))}</span>'


def _card(key: str, value: str, sub: str = "") -> str:
    return (f'<div class="card"><div class="k">{html.escape(key)}</div>'
            f'<div class="v">{value}</div>'
            + (f'<div class="s">{html.escape(sub)}</div>' if sub else "")
            + "</div>")


def render_login() -> str:
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Buergys Builds</title><style>{CSS}</style></head><body><div class="wrap">
<header class="top"><h1>Buergys <b>Builds</b></h1></header>
<div class="banner"><b>Token noetig.</b> Das Dashboard mit
<code>burgys dashboard</code> oeffnen, oder die URL mit
<code>?token=&lt;agent-token&gt;</code> aufrufen. Das Token steht in der
Tokendatei ausserhalb des Repositories.</div>
</div></body></html>"""


def render(controller, status: dict, viewer: str) -> str:
    cost = status["cost_guard"]
    queue = status["queue"]
    today = status["builds_today"]
    mac = status["mac_executor"]
    disk = status["disk"]

    mac_cls = {"AVAILABLE": "ok", "BUSY": "live", "OFFLINE": "idle"}.get(
        mac.get("availability", "OFFLINE"), "idle")
    cost_ok = not cost["paid_services_allowed"]

    system = "".join([
        _card("Windows Controller", _pill("ONLINE", "ok"),
              "Preflight, Tests, Queue, OTA - alles kostenlos"),
        _card("macOS Executor", _pill(mac.get("availability", "OFFLINE"), mac_cls),
              f"{mac.get('name', '?')}"
              + ("" if mac.get("produces_real_ipa") else " - erzeugt keine echte IPA")),
        _card("Cost Guard", _pill("AKTIV" if cost_ok else "FREIGEGEBEN",
                                  "ok" if cost_ok else "hot"),
              "PAID_SERVICES_ALLOWED=false" if cost_ok
              else "Kostenpflichtige Dienste sind freigegeben"),
        _card("Queue", f'{queue["length"]}',
              f'{len(queue["running"])} laufend'),
        _card("Builds heute", f'{today["total"]}',
              f'{today["success"]} ok, {today["failed"]} blockiert/fehlgeschlagen, '
              f'{today["dry_runs"]} Dry Runs'),
        _card("Speicher", f'{disk["free_gb"]} GB',
              f'frei - {disk["level"]}'),
    ])

    # -- projects -------------------------------------------------------
    rows = []
    for project in controller.registry.all():
        builds = controller.list_builds(project.id, limit=1)
        last = builds[0] if builds else None
        limit = controller.limiter.status(project.id)
        ex = status["mac_executors_per_project"].get(project.id, {})
        state = last.status if last else "-"
        rows.append(f"""<tr>
  <td><b>{html.escape(project.name)}</b><div class="muted">{html.escape(project.id)}
      &middot; <code>{html.escape(project.code)}</code></div></td>
  <td><div class="muted">{html.escape(project.repository.rsplit('/', 1)[-1])}</div>
      {html.escape(project.branch)}</td>
  <td>{html.escape(project.bundle_id)}</td>
  <td>{html.escape(project.marketing_version)}
      <div class="muted">Build {html.escape(str(controller.numbers.peek(project.id) - 1))}</div></td>
  <td>{html.escape(', '.join(project.modes))}</td>
  <td>{_pill(project.migration_state.replace('_', ' '),
             'ok' if project.migration_state.startswith('BURGYS') else 'warn')}</td>
  <td>{_pill(state, _pill_class(state)) if last else '<span class="muted">nie</span>'}
      {f'<div class="muted">{html.escape(last.build_id)}</div>' if last else ''}</td>
  <td>{limit['remaining']}/{limit['limit']}
      <div class="muted">{html.escape(ex.get('availability', '?'))}</div></td>
</tr>""")

    # -- recent builds ---------------------------------------------------
    build_rows = []
    for manifest in controller.list_builds(limit=15):
        ota = manifest.get("ota") or {}
        artifact = manifest.get("artifact_sha256")
        build_rows.append(f"""<tr>
  <td><code>{html.escape(manifest.build_id)}</code></td>
  <td>{html.escape(manifest.get('project_name') or manifest.get('project'))}</td>
  <td><code>{html.escape((manifest.get('commit') or '')[:8] or '-')}</code></td>
  <td>{html.escape(str(manifest.get('version')))} ({html.escape(str(manifest.get('build_number')))})</td>
  <td>{html.escape(manifest.get('mode') or '')}</td>
  <td>{_pill(manifest.display_status(), _pill_class(manifest.status))}</td>
  <td class="muted">{html.escape(str(manifest.get('mac_minutes') or 0))} min</td>
  <td>{'<code>' + html.escape(artifact[:12]) + '&hellip;</code>' if artifact
       else '<span class="muted">-</span>'}</td>
  <td>{'<a href="' + html.escape(ota.get('install_url', '')) + '">OTA</a>' if ota
       else '<span class="muted">-</span>'}</td>
</tr>""")

    # -- observability ---------------------------------------------------
    all_builds = controller.list_builds(limit=500)
    real = [m for m in all_builds if not m.is_dry_run]
    succeeded = [m for m in real if m.status == S.SUCCESS]
    minutes_by_project: dict[str, float] = {}
    for m in all_builds:
        minutes_by_project[m.get("project") or "?"] = round(
            minutes_by_project.get(m.get("project") or "?", 0.0)
            + float(m.get("mac_minutes") or 0), 2)
    rate = f"{100 * len(succeeded) // len(real)} %" if real else "-"
    last_success = succeeded[0].get("finished_at") if succeeded else "noch keiner"
    obs = "".join([
        _card("Erfolgsquote", rate, f"{len(succeeded)}/{len(real)} echte Builds"),
        _card("Letzter Erfolg", html.escape(str(last_success or "-")[:16]), ""),
        _card("macOS-Minuten", str(round(sum(minutes_by_project.values()), 1)),
              "gesamt - Grundlage fuer die Mac-mini-Rechnung"),
        _card("Metered", html.escape(", ".join(
            f"{k}: {v}" for k, v in (cost.get("metered") or {}).items()) or "nichts"),
            f"Periode {cost.get('period')}"),
    ])
    per_project_minutes = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v} min</td></tr>"
        for k, v in sorted(minutes_by_project.items())) or \
        '<tr><td colspan="2" class="muted">noch keine macOS-Zeit verbraucht</td></tr>'

    banner = ""
    if not mac.get("produces_real_ipa"):
        banner = ('<div class="banner"><b>Kein macOS-Executor.</b> Buergys Builds '
                  'erledigt Preflight, Tests, Queue, Versionierung und OTA-Vorbereitung '
                  'auf dem HP. Archive, Signing und Export brauchen einen Mac - '
                  'siehe <code>docs/MAC_EXECUTOR.md</code>. Bis dahin bleibt Codemagic '
                  'die einzige Quelle fuer echte IPAs.</div>')

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="20">
<title>Buergys Builds</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>Buergys <b>Builds</b></h1>
    <span class="tag">Windows-first iOS Build Controller</span>
    <span class="tag" style="margin-left:auto">angemeldet als {html.escape(viewer)}</span>
  </header>
  {banner}

  <h2>System</h2>
  <div class="grid">{system}</div>

  <h2>Projekte</h2>
  <table>
    <tr><th>App</th><th>Repository / Branch</th><th>Bundle ID</th><th>Version</th>
        <th>Modi</th><th>Migration</th><th>Letzter Build</th><th>Limit / Executor</th></tr>
    {''.join(rows) or '<tr><td colspan="8" class="muted">keine Projekte konfiguriert</td></tr>'}
  </table>
  <p class="actions">Aktionen ueber die CLI:
    <code>burgys preflight &lt;projekt&gt;</code> &middot;
    <code>burgys build &lt;projekt&gt; --dry-run</code> &middot;
    <code>burgys approve &lt;build-id&gt;</code> &middot;
    <code>burgys logs &lt;build-id&gt;</code> &middot;
    <code>burgys ota &lt;build-id&gt;</code></p>

  <h2>Letzte Builds</h2>
  <table>
    <tr><th>Build ID</th><th>Projekt</th><th>Commit</th><th>Version</th><th>Modus</th>
        <th>Status</th><th>macOS</th><th>SHA-256</th><th>OTA</th></tr>
    {''.join(build_rows) or '<tr><td colspan="9" class="muted">noch keine Builds</td></tr>'}
  </table>

  <h2>Observability</h2>
  <div class="grid">{obs}</div>
  <table style="margin-top:12px">
    <tr><th>Projekt</th><th>macOS-Minuten gesamt</th></tr>
    {per_project_minutes}
  </table>

  <footer>
    Buergys Builds - lokal auf 127.0.0.1, nichts davon ist oeffentlich erreichbar.
    Diese Seite aktualisiert sich alle 20 Sekunden.
  </footer>
</div>
</body>
</html>
"""
