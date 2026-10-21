"""Controller-side preflight for narrowly scoped trust-package updates."""

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def trust_update_conflicts(report, targets):
    conflicts = []
    installed = {canonicalize_name(k): v for k, v in report["packages"].items()}
    active = {
        k: v
        for k, v in targets.items()
        if k in installed and Version(installed[k]["version"]) < Version(v)
    }
    if "pip" in active and Version(
        report["marker_environment"]["python_version"]
    ) < Version("3.10"):
        conflicts.append("pip target requires Python >=3.10")
    for name, package in installed.items():
        for raw in package["requires"]:
            requirement = Requirement(raw)
            target = canonicalize_name(requirement.name)
            if target not in active:
                continue
            # Extras are resolver inputs, not persistent installation metadata.
            # Validate active base requirements; owning locks govern selected extras.
            if requirement.marker and not requirement.marker.evaluate(
                report["marker_environment"]
            ):
                continue
            if not requirement.specifier.contains(active[target], prereleases=True):
                conflicts.append(f"{name}: {raw} rejects {active[target]}")
    return conflicts


class FilterModule:
    def filters(self):
        return {
            "trust_update_conflicts": trust_update_conflicts,
            "trust_lock_replacement_safe": trust_lock_replacement_safe,
        }


def trust_lock_replacement_safe(before, after, target, wheel_hash=None):
    import tomllib

    original, replacement = tomllib.loads(before), tomllib.loads(after)
    old_packages = [
        p for p in original.get("package", []) if p.get("name") == "certifi"
    ]
    new_packages = [
        p for p in replacement.get("package", []) if p.get("name") == "certifi"
    ]
    if (
        len(old_packages) != 1
        or len(new_packages) != 1
        or new_packages[0]["version"] != target
    ):
        return False
    if wheel_hash and not any(
        w.get("hash") == "sha256:" + wheel_hash
        for w in new_packages[0].get("wheels", [])
    ):
        return False
    for lock in (original, replacement):
        lock["package"] = [p for p in lock["package"] if p.get("name") != "certifi"]
    return original == replacement
