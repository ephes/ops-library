# Opaq company synthetic viewer

Install, verify or roll back the reviewed **synthetic HTML-only** bundle from
`offline/opaq-company-viewer`. This role is an offline-tested candidate, not a
record of host enrollment or deployment. It does not install Traefik, assign DNS,
register FastDeploy, provision credentials, ingest data, or back up company state.
The disabled FastDeploy draft remains disabled.

## Contract

Only the three pinned synthetic pages and pinned viewer program are admitted.
The manifest is checked against independently pinned content and regenerated
systemd/Traefik configuration, not trusted as permission to publish arbitrary files.
The service uses `opaq-company-viewer`, loopback only, and the package's hardened
systemd unit. Traefik must already provide `web`, `web-secure`, TLS and its file
provider at `/etc/traefik/dynamic`. No global proxy files or services are changed.

A separately provisioned `/etc/opaq-company/viewer.htpasswd` is mandatory: regular,
nonempty, root-owned, mode 0640, and group-readable by the explicitly supplied
Traefik group. It is never read, copied, changed or removed by this role. Operators
must separately validate its credentials and Traefik readability. All HTTPS routes
require BasicAuth; cache headers precede authentication so 401 responses also
carry `private, no-store`. BasicAuth is not SSO/MFA; loopback trusts the host.

## Variables and use

- `opaq_viewer_action`: `install` (default), `verify`, or `rollback`.
- `opaq_viewer_bundle`: controller-side absolute bundle directory; default
  `CHANGEME`, required for install. Build it with the existing offline package tool.
- `opaq_viewer_proxy_group`: preexisting Traefik reader group; default `CHANGEME`.

```yaml
- hosts: explicitly_selected_private_target
  become: true
  roles:
    - role: local.ops_library.opaq_company_viewer_deploy
      opaq_viewer_bundle: /operator/synthetic-bundle
      opaq_viewer_proxy_group: CHANGEME
```

This example deliberately fails until private configuration is supplied. No
private inventory, credential identifier or target is part of this public role.
Python 3.11+, systemd, existing TLS ingress and explicitly approved native rollout
are prerequisites. Check mode refuses: it cannot prove activation or recovery.

## Install, verification and recovery

Controller admission precedes target transport; target admission precedes identity
creation and owned artifact writes. A first install
refuses existing owned paths or an occupied backend port. An existing dedicated
identity must have no login shell and no home. The system identity is retained on
rollback; it never owns unrelated data. Deployments are serialized by a role lock.
An unchanged install verifies service/content/unauthenticated HTTPS and reports
no change; it never overwrites the last rollback record.

The role retains one root-only rollback record in
`/var/lib/opaq-company-viewer-installer`. It captures only its six publication files
(three pages, viewer, unit, one dynamic proxy file), their metadata, and previous
service enabled/active state. Updates stop only this viewer before replacing content. Backend verification
precedes proxy publication;
final verification requires exact pages, private/no-store, and unauthenticated
HTTPS 401 with private/no-store on all three routes. It never uses credentials.
Failure restores owned files and prior service state, reports failure, and retains
the record. Interrupted installs require explicit rollback before retry. Reserved pending
files are recovered only when their bytes match a recorded synthetic artifact
(or its incomplete prefix); foreign pending content is refused. A rollback
refuses externally changed owned artifacts rather than overwriting them.

Use the same role with `opaq_viewer_action: rollback` for the immediately preceding
installation; verify with `opaq_viewer_action: verify`. First-install rollback removes
only owned files and empty viewer directories; credentials, dedicated identity,
shared directories, other proxy routes and global proxy state remain. Later rollback
restores the previous owned bytes/metadata. No general backup or uninstall is claimed.
An interruption during the very first journal write, before any publication
artifact is changed, or a crash during recovery can require operator inspection; do not delete the journal
or force overwrite. Host-native systemd/Traefik reload timing, certificate/auth
provisioning, route/port collisions outside these owned paths and restore operation
remain operator acceptance checks. Downloaded copies cannot be revoked by cache policy.

## Validation limits

Disposable filesystem tests with mocked identity/systemd/HTTP operations cover
admission, repeated install, failure recovery, interruption, scoped rollback and
metadata preservation. Existing real loopback viewer tests cover allowlisted HTTP
and cache/error behavior. Native Traefik's 401 header behavior, service hardening,
TLS, user provisioning and host operation are **not** proven by mocks. No real
inventory, financial files, hosts, credentials or deployment are used.
