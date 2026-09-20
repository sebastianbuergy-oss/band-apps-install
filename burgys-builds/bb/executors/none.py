"""The honest default: there is no Mac.

Sebastian owns a Windows PC.  Until he approves a macOS executor, every
macOS job is refused here with the reason spelled out, rather than silently
falling back to something that costs money.
"""
from __future__ import annotations

from ..errors import ExecutorUnavailable
from . import OFFLINE, MacExecutor, MacJob, MacJobResult, register


@register
class NoMacExecutor(MacExecutor):
    name = "none"
    cost_resource = "windows_local"
    produces_real_ipa = False

    def availability(self) -> str:
        return OFFLINE

    def submit(self, job: MacJob) -> str:
        raise ExecutorUnavailable(
            "Kein macOS-Executor konfiguriert. Buergys Builds hat alles "
            "erledigt, was auf Windows moeglich ist; der Archive-, Signing- "
            "und Export-Schritt braucht einen Mac. Optionen: "
            "GitHubMacExecutor (kostenlos fuer oeffentliche Repos, braucht "
            "Sebastians Freigabe fuer den ersten echten Lauf) oder ein "
            "eigener Mac mini als Burgys-iOS-Runner."
        )

    def poll(self, handle: str) -> MacJobResult:
        raise ExecutorUnavailable("Kein macOS-Executor konfiguriert")
