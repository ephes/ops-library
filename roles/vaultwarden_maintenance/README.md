# vaultwarden_maintenance

Deny or restore Vaultwarden ingress at Traefik for a maintenance window.

The role writes a single Traefik dynamic file containing a high-priority router
for the Vaultwarden host, fronted by an `ipAllowList` middleware. Sources outside
the allow list get `403` before reaching Vaultwarden; sources inside it pass
through to the normal service, which is what gives an operator a verification
path during the freeze. One router covers everything including live sync, since
Vaultwarden serves `/notifications/hub` on its main port. Removing the file ends the freeze, because Traefik
watches the dynamic directory.

## Why a separate file

The Echoport Vaultwarden backup archives the router file the deploy role owns
(`/etc/traefik/dynamic/vaultwarden.yml`), and its restore writes that file back
without reloading Traefik while gating only on a loopback health check.

If the maintenance state lived in that file, a restore from a backup taken
during a freeze would silently reinstate the deny router: every health check
green, every client — including the operator's own `bw` path — black-holed.

The role therefore refuses to run at all if `vaultwarden_maintenance_filename`
equals `vaultwarden_maintenance_archived_router_filename`. Both are plain
filenames, never paths, and the role builds the full path itself — so no caller
value can normalise into the archived router file through `./`, `//`, or `..`.
Keep the second variable pointing at whatever the backup runner actually
archives, and re-check it whenever that runner's file list changes.

## What the role deliberately does not do

No package, repository, or service tasks. It runs inside a maintenance window,
where an incidental `apt` upgrade and Vaultwarden restart would be an
unacceptable surprise. It also does not restart Traefik.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `vaultwarden_maintenance_state` | `absent` | `present` denies ingress, `absent` restores it |
| `vaultwarden_domain` | `CHANGEME` | deployed Vaultwarden `https://host` URL; the hostname is derived from it |
| `vaultwarden_maintenance_filename` | `vaultwarden-maintenance.yml` | the file this role owns, inside the dynamic dir |
| `vaultwarden_maintenance_archived_router_filename` | `vaultwarden.yml` | the file the backup archives; never written here |
| `vaultwarden_maintenance_traefik_entrypoint` | `web-secure` | must match the deploy role's entrypoint |
| `vaultwarden_maintenance_router_priority` | `100000` | must beat the deploy role's routers, whose priority is their rule length |
| `vaultwarden_maintenance_settle_seconds` | `5` | wait for Traefik to load a changed configuration before probing |
| `vaultwarden_maintenance_allow_source_ranges` | loopback | who may still reach Vaultwarden during the freeze |
| `vaultwarden_maintenance_verify_external` | `true` | probe the public endpoint |
| `vaultwarden_maintenance_probe_delegate` | `localhost` | where the probe runs from |
| `vaultwarden_maintenance_probe_expects_denial` | `true` | whether that vantage point is outside the allow list |
| `vaultwarden_maintenance_accept_unverified_denial` | `false` | required acknowledgement when it is not |
| `vaultwarden_maintenance_denied_status` | `403` | expected status while denied |
| `vaultwarden_maintenance_reachable_status` | `[200, 302]` | expected status once restored |
| `vaultwarden_maintenance_loopback_ports` | `[8000]` | ports checked for non-loopback listeners |

## Verification

Every run verifies the resulting state, because a freeze that is not verified is
not a freeze:

- no non-loopback listener on the Vaultwarden ports, so denial at Traefik
  actually implies unreachability
- an external probe of `<domain>/alive` from the declared vantage point,
  expecting `403` while denied and a reachable status once restored

What the probe proves, and what it does not: it establishes the ingress *state*
from the prober's vantage point — denied or reachable. It does not prove that
every attribute of a changed configuration is live, because a `403` looks the
same whether it came from the new router or a previous one that Traefik has not
replaced yet. The role waits `vaultwarden_maintenance_settle_seconds` after a
change before probing, but if you alter the allow list, entrypoint, priority, or
websocket setting of an already-active freeze, verify the specific change from a
source it actually affects.

If you widen the allow list to include the prober itself — the documented
operator path during a window — that run can no longer observe the denial. Say
so with `vaultwarden_maintenance_probe_expects_denial: false`; the role then
expects a reachable status and refuses to run at all unless
`vaultwarden_maintenance_accept_unverified_denial` is also set, so a freeze can
never be reported as verified by accident. Prefer probing from a host outside
the allow list.

Setting `vaultwarden_maintenance_verify_external: false` skips only the external
probe and says so loudly in the output. Do not use it for a real window.

Under `--check` the role does not change ingress, so the probe is skipped when
the requested state differs from the current one, and the run says so. A check
run whose state already matches still probes, which makes `--check` a useful
read-only confirmation that ingress is in the state you believe it is.

## Example

```yaml
- name: Freeze Vaultwarden ingress
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.vaultwarden_maintenance
      vars:
        vaultwarden_maintenance_state: present
        vaultwarden_domain: "https://vault.example.com"
```
