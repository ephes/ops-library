"""Prepare a synthetic offline hosting bundle; performs no deployment or registration."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat

CANDIDATE = "bd4e58bae6b9dce2c5c6941450e04c4086a6bfc3"  # pragma: allowlist secret -- reviewed synthetic content/revision hash
CURATED = Path("experiments/2026-10-03-store-consumer/store-preview")
SOURCES = {
    "accepted.html": "3cb6f78ba18899aa5f2727ab175c69c06d4aebc4352909334b275ad14b0238e8",  # pragma: allowlist secret -- reviewed synthetic content/revision hash
    "retained-last-good.html": "0b80c77a1e7f2e9e94f8bd875a3926363d9690200e22c24a911139591513c845",  # pragma: allowlist secret -- reviewed synthetic content/revision hash
    "no-accepted.html": "60352be9da40e3b67c73621f7543b51ebe20f92ce10ed2658423d4396bd0c1dc",  # pragma: allowlist secret -- reviewed synthetic content/revision hash
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def configuration(raw):
    config = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(config, dict) or set(config) != {
        "synthetic_only",
        "company",
        "hostname",
        "domain_assigned",
        "port",
    }:
        raise ValueError("exact offline configuration required")
    if (
        config["synthetic_only"] is not True
        or config["company"] != "synthetic-opaq"
        or config["domain_assigned"] is not False
    ):
        raise ValueError("unassigned synthetic company scope required")
    if (
        not isinstance(config["port"], int) or isinstance(config["port"], bool)
    ) or not 1024 <= config["port"] <= 65535:
        raise ValueError("explicit unprivileged offline port required")
    if not isinstance(config["hostname"], str):
        raise ValueError("hostname required")
    host = config["hostname"].encode("idna").decode("ascii").lower()
    if (
        len(host) > 253
        or "." not in host
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        )
    ):
        raise ValueError("DNS hostname required, not URL/routing expression")
    return dict(config, hostname=host)


def traefik(config):
    prefix = "opaq-company"
    host = config["hostname"]
    return {
        "http": {
            "routers": {
                prefix
                + "-secure": {
                    "rule": f"Host(`{host}`)",
                    "entryPoints": ["web-secure"],
                    "middlewares": [prefix + "-headers", prefix + "-auth"],
                    "service": prefix,
                    "tls": {},
                },
                prefix
                + "-http": {
                    "rule": f"Host(`{host}`)",
                    "entryPoints": ["web"],
                    "middlewares": [prefix + "-redirect"],
                    "service": "noop@internal",
                },
            },
            "middlewares": {
                prefix
                + "-auth": {
                    "basicAuth": {
                        "usersFile": "/etc/opaq-company/viewer.htpasswd",
                        "removeHeader": True,
                    }
                },
                prefix
                + "-headers": {
                    "headers": {
                        "contentTypeNosniff": True,
                        "referrerPolicy": "no-referrer",
                        "customFrameOptionsValue": "SAMEORIGIN",
                        "customResponseHeaders": {"Cache-Control": "private, no-store"},
                    }
                },
                prefix
                + "-redirect": {
                    "redirectScheme": {"scheme": "https", "permanent": True}
                },
            },
            "services": {
                prefix: {
                    "loadBalancer": {
                        "servers": [{"url": f"http://127.0.0.1:{config['port']}"}]
                    }
                }
            },
        }
    }


def unit(config):
    # Same loopback/systemd model and hardening as static_site_deploy; separate identity.
    return f"""[Unit]
Description=Opaq synthetic company HTML viewer
After=network.target

[Service]
Type=simple
User=opaq-company-viewer
Group=opaq-company-viewer
ExecStart=/usr/bin/python3 /usr/local/libexec/opaq-company-httpd.py --root /srv/opaq-company/view --port {config['port']}
Restart=on-failure
RestartSec=2
UMask=0027
TasksMax=128
MemoryMax=256M
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectClock=true
ProtectControlGroups=true
ProtectHome=true
ProtectHostname=true
ProtectKernelLogs=true
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_INET
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
CapabilityBoundingSet=
AmbientCapabilities=
ReadOnlyPaths=/srv/opaq-company/view

[Install]
WantedBy=multi-user.target
"""


def build(candidate_root, config, output):
    config = configuration(config)
    candidate_root, output = Path(candidate_root), Path(output)
    content = {}
    for name, expected in SOURCES.items():
        path = candidate_root / CURATED / name
        for component in (path, *path.parents):
            if component == candidate_root.parent:
                break
            if component.is_symlink():
                raise ValueError("no source symlink admission")
        if (
            not stat.S_ISREG(path.lstat().st_mode)
            or path.stat().st_size > 2 * 1024 * 1024
        ):
            raise ValueError("bounded regular curated HTML required")
        raw = path.read_bytes()
        if sha(raw) != expected:
            raise ValueError("curated synthetic source hash mismatch")
        content["view/" + ("index.html" if name == "accepted.html" else name)] = raw
    content["opaq-company-httpd.py"] = (
        Path(__file__).with_name("viewer.py").read_bytes()
    )
    content["opaq-company-viewer.service"] = unit(config).encode()
    # JSON is valid YAML; no templating/escaping ambiguity in Traefik fields.
    content["opaq-company.traefik.yml"] = (
        json.dumps(traefik(config), indent=2).encode() + b"\n"
    )
    content["fastdeploy-registration.draft.json"] = (
        json.dumps(
            {
                "status": "disabled-draft-not-registered",
                "role": "local.ops_library.fastdeploy_register_service",
                "vars": {
                    "fd_service_name": "opaq-company-viewer-code",
                    "fd_service_description": "Deploy company viewer code only; no ingestion",
                    "fd_ops_control_method": "git",
                    "fd_ops_control_git": "CHANGEME",
                    "fd_ops_control_ref": "CHANGEME_PINNED_REVISION",
                    "fd_sync_services": False,
                    "fd_context_defaults": {
                        "FILTER": "opaq-company-viewer-code",
                        "LIMIT": "CHANGEME",
                    },
                },
                "missing": [
                    "authorized private code-only playbook",
                    "target/port/TLS verification",
                    "private SOPS auth provisioning",
                ],
                "excluded": [
                    "source credentials",
                    "database mounts",
                    "ingestion/scheduler",
                    "backup enrollment",
                ],
            },
            indent=2,
        ).encode()
        + b"\n"
    )
    manifest = {
        "format": "opaq.synthetic.offline-viewer.v1",
        "synthetic_only": True,
        "company": "synthetic-opaq",
        "source_candidate": CANDIDATE,
        "hostname": config["hostname"],
        "domain_assigned": False,
        "deployment_authorized": False,
        "content": {name: sha(raw) for name, raw in sorted(content.items())},
    }
    # Claim output exclusively before writing. A partial draft is never a deploy action.
    output.mkdir(mode=0o700)
    try:
        (output / "view").mkdir(mode=0o700)
        for name, raw in content.items():
            path = output / name
            with path.open("xb") as stream:
                path.chmod(0o600)
                stream.write(raw)
        with (output / "manifest.json").open("x") as stream:
            (output / "manifest.json").chmod(0o600)
            stream.write(json.dumps(manifest, indent=2) + "\n")
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        manifest = build(
            args.candidate_root, Path(args.config).read_text(), args.output
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Offline package refused: {type(exc).__name__}\n")
    print(json.dumps({"format": manifest["format"], "files": len(manifest["content"])}))
