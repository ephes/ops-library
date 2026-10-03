# Offline synthetic company viewer package

This is an offline preparation tool, **not an installed Opaq service or Ansible
deployment role**. It admits only three hash-pinned fictional company HTML views
from the reviewed Daybook integrated candidate
`bd4e58bae6b9dce2c5c6941450e04c4086a6bfc3`. No source applications, bank access,
company/personal database, raw receipt, source credential, inventory, DNS or
Echoport target is read or changed. Shared software does not mean shared state.

## Prepare locally

From the ops-library root, copy `offline/opaq-company-viewer/config.example.json`
to a disposable location. Set `port` to an integer for offline rendering; the
`CHANGEME` default refuses output. Example `10063` is **not reserved on any host**.
Keep `synthetic_only: true`, `company: synthetic-opaq`, `domain_assigned: false`.
The hostname is configurable; `opaq.home.wersdörfer.de` is a proposal, rendered
as `opaq.home.xn--wersdrfer-47a.de`, not assigned DNS or verified TLS coverage.

```sh
python3 offline/opaq-company-viewer/package.py \
  --candidate-root /path/to/reviewed/daybook-candidate \
  --config /tmp/opaq-offline-config.json \
  --output /tmp/opaq-offline-bundle
uv run pytest -q tests/test_opaq_offline_viewer.py
```

Choose a fresh output path. Preparation makes no host connections, executes no
Ansible, registers no service and never overwrites an existing bundle. It copies
exact pinned HTML bytes: accepted company cash, retained last-good history and
initial unknown cash. Unknown files, DBs and raw evidence are never copied.
Wrong/missing/modified/symlinked admitted inputs or configuration scope/injection
are refused. The fixed fixture hashes intentionally refuse changed or real views;
real snapshot enrollment needs its own reviewed producer/delivery contract.

## Bundle boundary

- `view/`: `index.html`, `retained-last-good.html`, `no-accepted.html` only.
- `opaq-company-httpd.py`: exact HTML routes, IPv4 loopback, GET/HEAD, no listing,
  no uploads, no URL/credential logging, `private, no-store` even on errors.
- `opaq-company-viewer.service`: dedicated company identity, read-only system/home
  hardening and content directory; no environment/DB/source credentials or writer.
- `opaq-company.traefik.yml`: one authenticated TLS content router; **no LAN or
  Tailscale bypass**. HTTP routes only to HTTPS redirect, never to content. JSON
  serialization is valid YAML and prevents hostname/template expression injection.
- `fastdeploy-registration.draft.json`: disabled registration inputs for existing
  `fastdeploy_register_service`; no executable registration/playbook is provided.
- `manifest.json`: configuration/provenance and every bundle member hash. It is
  outside the served directory; hashes are consistency evidence, not signatures.

The implementation follows `static_site_deploy` loopback/systemd and homelab
Traefik file-provider conventions, and the existing FastDeploy registration role.
Those roles remain unchanged. Their generic public routes/no-cache setting and
LAN auth bypass are not imported. TLS BasicAuth uses a private owner-only bcrypt
`usersFile`, strips Authorization before forwarding, and applies to all content
paths. Headers wrap authentication so early 401 responses also receive no-store.
The viewer is not an MFA/SSO/RBAC implementation. Anyone with direct local
loopback access could bypass proxy authentication; host trust and process identity
must be verified before real use. Systemd limits/hardening are proposed, not run
on macmini. HTML still includes unsaved fictional scenario controls; no transfer,
posting, accepted receipt decision or persisted edit is introduced.

Private response headers discourage browser/shared caching, but cannot revoke
already downloaded copies. Configure sensitive Traefik access logs to omit
Authorization and confidential paths/payloads before onboarding. Server request
logging is disabled; global proxy configuration is outside this offline bundle.

## Narrow later rollout and rollback

These are operator steps for a **separately authorized synthetic deployment**,
not commands to run as part of preparing the bundle:

1. Verify target Ubuntu/systemd/Python, patched Traefik/file provider, free port,
   hostname/DNS/TLS and reserved service/path ownership. Check for conflicting
   routers. Create the dedicated unprivileged `opaq-company-viewer` identity with
   no home/source access. Keep root-owned code/config, company-viewer-readable
   HTML only, no producer state/evidence/native DB mounts.
2. Provision owner bcrypt authentication through private ops-control SOPS, with
   `/etc/opaq-company/viewer.htpasswd` readable by Traefik only (root-owned,
   restricted Traefik group). No password/hash/key is supplied by this bundle.
   Verify missing/invalid usersFile fails closed with the installed proxy.
3. Use a responsible private code-only playbook and existing FastDeploy role to
   install a pinned reviewed bundle. The registration draft intentionally lacks
   repository/target/ref enrollment and that playbook. Code CI can build/test
   synthetic artifacts; it must not acquire source credentials or collect data.
4. With the viewer stopped, install the entire immutable synthetic view revision,
   verify the manifest, install code/unit/config, validate systemd/Traefik on the
   actual target, then start the viewer and route. Authenticate on LAN/Tailscale
   and externally: every HTML/error path must be private/no-store, anonymous
   content requests denied, credentials removed upstream. No snapshot JSON,
   DB/evidence, manifest, auth file or status directory is served.
5. Roll back by disabling the new route, stopping only this viewer, and restoring
   its previous verified code/config/content as a whole. Revalidate and restore
   the route. First-install rollback removes only explicitly owned files/account
   after checking ownership; no global proxy restart/removal or state deletion.

Data ingestion is a separate company producer capability on Atlas, not code CI,
FastDeploy or a second macmini scheduler. No delivery/import endpoint is added.
Future company snapshot delivery, active-revision selection and stale-state
handling remain P/ops responsibilities; a generated curated page is not evidence
of current collection or a real balance. Current Receipts Space/MoneyMoney/Bill2
remain unchanged. Future personal services require independent state/access and
restore units; none is commissioned here.

## Backup and remaining decisions

The viewer receives reproducible snapshot-derived HTML only. Durable company
SQLite/evidence/pointer recovery belongs to the reviewed producer recovery
contract, **not this viewer or an enrolled Echoport target**. Separate forecast
vintages/code pins must be recoverable to rebuild charts. Later ops work should
preserve selected revision/code/config manifests for availability/rollback, and
securely recover auth/keys separately. No encryption/off-site/retention guarantee.

Before live adoption decide/verify hostname assignment, target and port, owner
credential delivery, actual TLS/proxy versions, private code deployment playbook,
company revision transport/enrollment and monitored freshness, plus production
backup/restore coverage. Synthetic preparation needs no bank/source facts.
No live financial import, infrastructure mutation, deployment, merge or push is
authorized or claimed by this tool.
