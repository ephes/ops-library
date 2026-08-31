# Certbot DNS Deploy Role

Obtain and renew wildcard (and apex) TLS certificates via Certbot using DNS-01.

## Description

This role installs Certbot with the DNS plugin, renders provider credentials, requests a single lineage containing the apex and wildcard for a domain, and configures renewal hooks so dependent services (e.g., Traefik, Postfix, Dovecot) load the renewed certificate. The built-in `certbot.timer` is enabled to keep certificates fresh.

## Requirements

- Debian/Ubuntu with `systemd`
- DNS provider: Gandi LiveDNS (others can be added later)
- Root privileges to install packages and write `/etc/letsencrypt`
- Gandi credential must be a LiveDNS API key (not a Personal Access Token). UI path: avatar (top right) → User settings → “Password & access restrictions” → Developer access → API key (marked deprecated but still works for LiveDNS).

## Role Variables

### Required

```yaml
certbot_dns_provider: "gandi"          # Only gandi supported today
certbot_dns_domain: "home.xn--wersdrfer-47a.de"
certbot_dns_email: "admin@wersdoerfer.de"
certbot_dns_gandi_api_token: "CHANGEME"  # Gandi LiveDNS API key
```

### Common configuration

```yaml
certbot_dns_wildcard: true                 # Include *.domain
certbot_dns_include_base: true             # Include apex domain
certbot_dns_additional_domains: []         # Extra SANs
certbot_dns_key_type: "ecdsa"              # rsa|ecdsa
certbot_dns_staging: false                 # Use LE staging for tests
certbot_dns_propagation_seconds: 120       # Wait for DNS propagation
certbot_dns_renewal_hooks: []              # Commands to run post-renewal
certbot_dns_credentials_file: "/etc/letsencrypt/dns-credentials.ini"
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

- **1.0.0** (2025-12-02): Initial release

## License

MIT

## Author Information

Jochen Wersdoerfer
