"""D22: the page's Node supply chain is pinned. Exact versions, an exact Node, no install scripts.

A caret, a tilde, a range, a tag or a URL in `package.json` fails here, and so does a lockfile
that no longer matches it, which `npm ci` would also reject, or that locks a package from outside
the npm registry, without a hash, as a link or with an install script other than `fsevents`.
The two-week cooldown is checked against the registry when the lockfile is regenerated (ADR 0006);
this test cannot reach the network.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

WEB = Path(__file__).resolve().parents[2] / "apps" / "web"
EXACT = re.compile(r"\d+\.\d+\.\d+")
DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")
INSTALL_SCRIPTS = ("preinstall", "install", "postinstall", "prepublish", "prepare")


def package() -> dict[str, Any]:
    return json.loads((WEB / "package.json").read_text())  # type: ignore[no-any-return]


def lock() -> dict[str, Any]:
    return json.loads((WEB / "package-lock.json").read_text())  # type: ignore[no-any-return]


def direct_dependencies() -> dict[str, str]:
    data = package()
    return {name: v for field in DEPENDENCY_FIELDS for name, v in data.get(field, {}).items()}


def test_every_dependency_is_an_exact_version() -> None:
    dependencies = direct_dependencies()
    assert dependencies
    loose = {name: v for name, v in dependencies.items() if not EXACT.fullmatch(v)}
    assert loose == {}


def test_no_field_can_move_a_version_behind_the_manifest() -> None:
    data = package()
    assert "peerDependencies" not in data
    assert "overrides" not in data
    assert "resolutions" not in data


def test_the_manifest_declares_no_install_script() -> None:
    scripts = package().get("scripts", {})
    assert [name for name in INSTALL_SCRIPTS if name in scripts] == []


def test_node_is_pinned_by_nvmrc_and_engines_to_the_same_exact_version() -> None:
    pinned = (WEB / ".nvmrc").read_text().strip()
    assert EXACT.fullmatch(pinned)
    assert package()["engines"] == {"node": pinned}


def test_npmrc_saves_exact_versions_enforces_engines_and_skips_install_scripts() -> None:
    lines = {line.strip() for line in (WEB / ".npmrc").read_text().splitlines()}
    assert {"save-exact=true", "engine-strict=true", "ignore-scripts=true"} <= lines


def test_the_lockfile_pins_the_same_versions_as_the_manifest() -> None:
    packages = lock()["packages"]
    assert lock()["lockfileVersion"] == 3
    root = packages[""]
    expected = {f: package().get(f, {}) for f in DEPENDENCY_FIELDS}
    assert {f: root.get(f, {}) for f in DEPENDENCY_FIELDS} == expected
    installed = {
        name: packages[f"node_modules/{name}"]["version"] for name in direct_dependencies()
    }
    assert installed == direct_dependencies()


def test_every_locked_package_comes_from_the_npm_registry_with_an_integrity_hash() -> None:
    entries = {path: v for path, v in lock()["packages"].items() if path}
    assert entries
    odd = [
        path
        for path, v in entries.items()
        if not v.get("inBundle")  # shipped inside its parent's tarball, which is hashed
        and not (
            v.get("resolved", "").startswith("https://registry.npmjs.org/")
            and v.get("integrity", "").startswith("sha512-")
        )
    ]
    assert odd == []


def test_the_lockfile_has_no_link_entry() -> None:
    links = [path for path, v in lock()["packages"].items() if v.get("link")]
    assert links == []


def test_only_the_documented_package_has_an_install_script() -> None:
    # fsevents (macOS only) ships prebuilt; installs run with scripts ignored anyway (ADR 0006).
    scripted = {path for path, v in lock()["packages"].items() if v.get("hasInstallScript")}
    assert scripted <= {"node_modules/fsevents"}


@pytest.mark.parametrize("name", [".nvmrc", ".npmrc", "package.json", "package-lock.json"])
def test_the_pin_files_exist(name: str) -> None:
    assert (WEB / name).is_file()
