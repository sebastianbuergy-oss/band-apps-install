"""Machine inventory (master brief, section 3).

Run on the machine you want to know about.  It reports what is there, not
what should be there, and it never prints the contents of a credential.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = [
    ("git", ["git", "--version"]),
    ("python", [sys.executable, "--version"]),
    ("node", ["node", "--version"]),
    ("npm", ["npm", "--version"]),
    ("gh", ["gh", "--version"]),
    ("flutter", ["flutter", "--version"]),
    ("dart", ["dart", "--version"]),
    ("xcodegen", ["xcodegen", "--version"]),
    ("fastlane", ["fastlane", "--version"]),
    ("ssh", ["ssh", "-V"]),
    ("7z", ["7z", "i"]),
    ("pwsh", ["pwsh", "-Version"]),
]


def _run(cmd: list) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        return "NICHT INSTALLIERT"
    try:
        res = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                             timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Fehler: {exc}"
    out = (res.stdout or res.stderr).strip().splitlines()
    return out[0] if out else "(keine Ausgabe)"


def report() -> str:
    lines = ["# Bestandsaufnahme", ""]
    lines += [
        "## Rechner", "",
        f"- System: {platform.system()} {platform.release()} ({platform.version()})",
        f"- Architektur: {platform.machine()}",
        f"- Prozessor: {platform.processor() or 'unbekannt'}",
        f"- Logische Kerne: {os.cpu_count()}",
        f"- Python: {platform.python_version()} ({sys.executable})",
        "",
    ]
    try:
        usage = shutil.disk_usage(str(Path.home()))
        lines.append(f"- Speicher (Home): {usage.free / 2 ** 30:.1f} GB frei von "
                     f"{usage.total / 2 ** 30:.1f} GB")
    except OSError:
        pass
    lines += ["", "## Werkzeuge", ""]
    for name, cmd in TOOLS:
        lines.append(f"- {name}: {_run(cmd)}")
    lines += ["", "## Apple-spezifisch", ""]
    for name in ("xcodebuild", "codesign", "security", "altool", "xcrun"):
        lines.append(f"- {name}: {'vorhanden' if shutil.which(name) else 'nicht vorhanden'}")
    lines += [
        "", "## SSH", "",
        f"- ~/.ssh vorhanden: {(Path.home() / '.ssh').exists()}",
        f"- Schluesseldateien: "
        + (", ".join(sorted(p.name for p in (Path.home() / '.ssh').glob('id_*')
                            if not p.name.endswith('.pub')))
           if (Path.home() / '.ssh').exists() else "keine")
        + "  (nur Dateinamen - Inhalte werden nie ausgegeben)",
        "",
    ]
    return "\n".join(lines) + "\n"
