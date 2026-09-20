"""Shared fixtures: a throwaway controller over a throwaway data root."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bb.builds import BuildController          # noqa: E402
from bb.config import load_config              # noqa: E402
from bb.projects import Project, Registry      # noqa: E402

FIXTURE_PROJECT = {
    "id": "testapp",
    "name": "Test App",
    "code": "TST",
    "repository": "https://example.invalid/testapp",
    "branch": "main",
    "kind": "xcodegen-webview",
    "bundle_id": "com.example.testapp",
    "scheme": "TestApp",
    "display_name": "Test App",
    "marketing_version": "1.0",
    "team_id": "TEAM123456",
    "preflight_command": [],
    "required_files": ["project.yml", "web/index.html"],
    "signing": {
        "AD_HOC": {
            "profile_name": "TestApp adhoc",
            "certificate_common_name": "Apple Distribution: Test (TEAM123456)",
            "expires": "2099-01-01",
            "certificate_expires": "2099-01-01",
            "expects_provisioned_devices": True,
        }
    },
    "ota": {"slug": "testapp", "title": "Test App"},
    "modes": ["AD_HOC", "APP_STORE_RELEASE"],
    "migration_state": "CODEMAGIC_ACTIVE",
    "enabled": True,
}


def make_checkout(root: Path, *, bundle_id: str = "com.example.testapp",
                  display_name: str = "Test App", commit: bool = True) -> Path:
    """A minimal repository that passes preflight."""
    import subprocess

    root.mkdir(parents=True, exist_ok=True)
    (root / "project.yml").write_text(
        "settings:\n  base:\n"
        f"    MARKETING_VERSION: '1.0'\n"
        f"    CURRENT_PROJECT_VERSION: '1'\n"
        f"    PRODUCT_BUNDLE_IDENTIFIER: {bundle_id}\n"
        "targets:\n  TestApp:\n    info:\n      properties:\n"
        f"        CFBundleDisplayName: {display_name}\n",
        encoding="utf-8")
    (root / "web").mkdir(exist_ok=True)
    (root / "web" / "index.html").write_text(
        '<meta name="viewport" content="width=device-width,viewport-fit=cover">'
        "<p>hallo</p>", encoding="utf-8")
    if commit:
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
               "PATH": __import__("os").environ.get("PATH", ""), "HOME": str(root)}
        run = lambda *a: subprocess.run(["git", "-C", str(root), *a],  # noqa: E731
                                        capture_output=True, env=env, check=True)
        run("init", "-q", "-b", "main")
        run("add", "-A")
        run("commit", "-q", "-m", "fixture")
    return root


def make_ipa(path, *, bundle_id="com.example.testapp", version="1.0",
             build_number="1", scheme="TestApp", team="TEAM123456",
             profile_name="TestApp adhoc", devices=2, get_task_allow=False,
             provisions_all_devices=False, signed=True, web=True,
             expires="2099-01-01T00:00:00") -> Path:
    """Build a synthetic .ipa that bb.ipa can read.

    An IPA is a zip with a binary plist and a CMS blob whose payload is XML.
    :func:`bb.ipa.inspect` slices the XML out rather than parsing CMS, so a
    fixture only has to put a real plist where the real thing would be.  That
    lets the verification tests run everywhere instead of only on a machine
    that happens to have a 5 MB signed artifact lying next to the checkout.
    """
    import datetime
    import plistlib
    import zipfile

    prefix = f"Payload/{scheme}.app/"
    info = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": scheme,
        "CFBundleDisplayName": scheme,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build_number,
        "CFBundleExecutable": scheme,
        "MinimumOSVersion": "16.0",
        "DTSDKName": "iphoneos26.5",
        "ITSAppUsesNonExemptEncryption": False,
    }
    profile = {
        "Name": profile_name,
        "UUID": "00000000-0000-0000-0000-000000000000",
        "TeamName": "Test Team",
        "TeamIdentifier": [team],
        "CreationDate": datetime.datetime(2026, 1, 1),
        "ExpirationDate": datetime.datetime.fromisoformat(expires),
        "Entitlements": {
            "application-identifier": f"{team}.{bundle_id}",
            "com.apple.developer.team-identifier": team,
            "get-task-allow": get_task_allow,
        },
        "DeveloperCertificates": [b"not-a-real-certificate"],
    }
    if devices:
        profile["ProvisionedDevices"] = [f"device{i:040d}" for i in range(devices)]
    if provisions_all_devices:
        profile["ProvisionsAllDevices"] = True
    # Wrap the XML plist the way a .mobileprovision does: arbitrary bytes
    # before and after, XML in the middle.
    blob = b"\x30\x82CMS-ish-header" + plistlib.dumps(
        profile, fmt=plistlib.FMT_XML) + b"trailing-signature-bytes"

    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(prefix + "Info.plist", plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
        z.writestr(prefix + "embedded.mobileprovision", blob)
        if signed:
            z.writestr(prefix + "_CodeSignature/CodeResources", "<plist/>")
        if web:
            z.writestr(prefix + "web/index.html", "<p>hallo</p>")
    return path


class ControllerCase(unittest.TestCase):
    """Base class giving every test its own data root and checkout."""

    project_overrides: dict = {}
    config_overrides: dict = {}

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.checkout = make_checkout(self.tmp / "checkout")
        data = json.loads(json.dumps(FIXTURE_PROJECT))
        data["local_path"] = str(self.checkout)
        data.update(self.project_overrides)
        self.project_data = data
        self.config = load_config(env={"BURGYS_DATA": str(self.tmp / "data"),
                                       "BURGYS_API_TOKEN_FILE": str(self.tmp / "tokens.json")})
        self.config["default_executor"] = "dryrun"
        self.config["require_approval_for_mac_builds"] = False
        self.config.update(self.config_overrides)
        self.controller = BuildController(self.config, Registry([Project(data)]))

    def rebuild_controller(self, **config_overrides) -> BuildController:
        """A *second* controller over the same data root - restart simulation."""
        config = load_config(env={"BURGYS_DATA": str(self.tmp / "data"),
                                  "BURGYS_API_TOKEN_FILE": str(self.tmp / "tokens.json")})
        config["default_executor"] = self.config["default_executor"]
        config["require_approval_for_mac_builds"] = \
            self.config["require_approval_for_mac_builds"]
        config.update(config_overrides)
        return BuildController(config, Registry([Project(self.project_data)]))
