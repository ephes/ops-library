# Certbot DNS Deploy Role

Obtain and renew wildcard (and apex) TLS certificates via Certbot using DNS-01.

## Description

This role installs Certbot with the DNS plugin, renders provider credentials, requests a single lineage containing the apex and wildcard for a domain, and configures renewal hooks so dependent services (e.g., Traefik, Postfix, Dovecot) load the renewed certificate. The built-in `certbot.timer` is enabled to keep certificates fresh.

## Requirements

- Debian/Ubuntu with `systemd`
- DNS provider: Gandi LiveDNS (`gandi`) or any RFC 2136 server accepting
  TSIG-signed updates (`rfc2136`, e.g. BIND with an `update-policy`)
- Root privileges to install packages and write `/etc/letsencrypt`
- Gandi credential must be a LiveDNS API key (not a Personal Access Token). UI path: avatar (top right) → User settings → “Password & access restrictions” → Developer access → API key (marked deprecated but still works for LiveDNS).

## Role Variables

### Required

```yaml
certbot_dns_provider: "gandi"          # gandi | rfc2136
certbot_dns_domain: "home.xn--wersdrfer-47a.de"
certbot_dns_email: "admin@wersdoerfer.de"
certbot_dns_gandi_api_token: "CHANGEME"  # Gandi LiveDNS API key
```

### RFC 2136 provider

```yaml
certbot_dns_provider: "rfc2136"
certbot_dns_rfc2136_server: "192.0.2.53"      # IP of the zone's primary (no hostname)
certbot_dns_rfc2136_port: 53
certbot_dns_rfc2136_key_name: "acme-home"     # TSIG key name
certbot_dns_rfc2136_key_secret: "CHANGEME"    # base64 secret, from SOPS
certbot_dns_rfc2136_key_algorithm: "HMAC-SHA256"
```

The key needs permission to add and delete `TXT` records at
`_acme-challenge.<name>` for every requested name. For an apex plus wildcard
certificate both challenges use the same owner name, so one BIND rule suffices:

```
update-policy { grant "acme-home" name _acme-challenge.home.example.com. TXT; };
```

The plugin finds the zone by asking the server for the SOA of the challenge name,
so `_acme-challenge.<domain>` may live in a delegated child zone. Updates go to
the primary; secondaries follow via NOTIFY, and `certbot_dns_propagation_seconds`
(default 120) covers the transfer.

### Switching provider on an existing lineage

`certbot certonly --keep-until-expiring` does not touch a lineage that is not due
for renewal, so it would keep renewing with the old authenticator. With
`certbot_dns_reconfigure_on_provider_change: true` (default) the role reads
`renewal/<cert-name>.conf` and, when its `authenticator` differs from
`dns-<certbot_dns_provider>`, runs `certbot reconfigure` with the new provider.
reconfigure does a dry-run challenge against the Let's Encrypt staging CA and
only saves the new settings if it succeeds, so a provider that cannot publish
the TXT record fails the deploy instead of failing the next renewal silently.
Needs certbot >= 2.3 (Ubuntu 24.04 ships 2.9). Each provider has its own
credentials file, so the old provider's file stays intact: after a failed
switch the lineage still renews with its previous provider, and other lineages
that use the old file are not affected. Only run the switch once the
zone is actually served by the new provider's servers (the delegation has moved),
because Let's Encrypt resolves the challenge through public DNS.

### Common configuration

```yaml
certbot_dns_wildcard: true                 # Include *.domain
certbot_dns_include_base: true             # Include apex domain
certbot_dns_additional_domains: []         # Extra SANs
certbot_dns_key_type: "ecdsa"              # rsa|ecdsa
certbot_dns_staging: false                 # Use LE staging for tests
certbot_dns_propagation_seconds: 120       # Wait for DNS propagation
certbot_dns_renewal_hooks: []              # Commands to run post-renewal
certbot_dns_credentials_file: "/etc/letsencrypt/dns-credentials.ini"            # gandi
certbot_dns_rfc2136_credentials_file: "/etc/letsencrypt/dns-rfc2136-credentials.ini"
certbot_dns_renewal_hook_path: "/etc/letsencrypt/renewal-hooks/deploy/reload-services.sh"
```

See `defaults/main.yml` for the full list.

## Example Playbook

```yaml
- name: Deploy Certbot DNS
  hosts: macmini
  become: true
  vars:
    dns_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/dns.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.certbot_dns_deploy
      vars:
        certbot_dns_provider: "gandi"
        certbot_dns_domain: "home.xn--wersdrfer-47a.de"
        certbot_dns_email: "admin@wersdoerfer.de"
        certbot_dns_gandi_api_token: "{{ dns_secrets.gandi_api_key }}"
        certbot_dns_renewal_hooks:
          - "systemctl restart traefik"
          - "systemctl reload postfix@-"
          - "systemctl reload dovecot"
```

Traefik's file provider watches its dynamic configuration files, not changes to
the Certbot symlink targets. Always use `systemctl restart traefik` after Certbot
rotates a file-provider certificate; a service reload does not make Traefik
re-read those external files. The restart briefly interrupts proxied connections.

The role installs one Bash deploy hook at `certbot_dns_renewal_hook_path`. Each
configured item runs in an isolated fail-fast block, every item is attempted, and
the script exits non-zero if any item fails. Keep required commands unmasked and
use one item per independent consumer, as in the example. Items do not share shell
variables, exported values, or working-directory changes. On a multi-lineage
host, an item may inspect Certbot's `${RENEWED_LINEAGE:-}` deploy-hook variable
and `exit 0` from its isolated block when that consumer does not use the renewed
lineage. The empty default is intentional: each deployment must explicitly name
its certificate consumers. Updating this public role does not rewrite downstream
inventory; migrate the effective hook list in the same rollout.

If items have prerequisite or shared-state relationships, combine them into one
multi-line item so that block remains fail-fast. A later independent item still
runs when that block fails, and the final script status reports the failure. On
Ubuntu's multi-instance Postfix packaging, target the active `postfix@-` instance;
`postfix.service` is a meta unit whose reload may be a successful no-op.

Certbot renews the lineage before invoking the deploy hook. If a hook fails, the
next timer run sees a current certificate and does not retry it. Some Certbot
directory-hook runners log the failure without failing the overall renewal, so
inspect its journal and Let's Encrypt log for `renewal hook item` or
`returned error code` rather than relying only on the unit result. The hook
diagnostic includes the renewed lineage. Correct the failure, then run
`RENEWED_LINEAGE=/etc/letsencrypt/live/<cert-name> /etc/letsencrypt/renewal-hooks/deploy/reload-services.sh`
(using the configured `certbot_dns_renewal_hook_path`; the shown path is its
default) or manually restart or reload each consumer that did not load the
renewed certificate.

Traefik (file provider) can read the resulting lineage:

```yaml
tls:
  certificates:
    - certFile: "/etc/letsencrypt/live/home.xn--wersdrfer-47a.de/fullchain.pem"
      keyFile: "/etc/letsencrypt/live/home.xn--wersdrfer-47a.de/privkey.pem"
```

## Handlers

None. Service reloads or restarts are handled via `certbot_dns_renewal_hooks`.

## Tags

- `certbot_dns` – run all tasks in this role

## Testing

```bash
# From repo root
just test-role certbot_dns_deploy
```

## Changelog

- **Unreleased**: `rfc2136` provider; automatic `certbot reconfigure` when the provider changes
- **1.0.0** (2025-12-02): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
