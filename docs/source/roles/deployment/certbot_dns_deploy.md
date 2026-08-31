# Certbot DNS Deploy

Role to obtain and renew wildcard/apex TLS certificates via Certbot using DNS-01 (Gandi LiveDNS).

- Installs certbot + dns-gandi plugin
- Renders provider credentials (Gandi LiveDNS API key)
- Requests a single lineage with apex + wildcard SANs
- Configures renewal hooks so dependent services load the renewed certificate
- Uses system `certbot.timer` for renewals

## Requirements

- Debian/Ubuntu with `systemd`
- Gandi LiveDNS domain and API key (not PAT). UI path: avatar → User settings → “Password & access restrictions” → Developer access → API key (deprecated label but works for LiveDNS).

## Variables (common)

- `certbot_dns_domain`: base domain (punycode if IDN), e.g. `home.xn--wersdrfer-47a.de`
- `certbot_dns_email`: Let’s Encrypt account email
- `certbot_dns_gandi_api_token`: LiveDNS API key
- `certbot_dns_wildcard`: include `*.domain` (default: true)
- `certbot_dns_include_base`: include apex (default: true)
- `certbot_dns_additional_domains`: extra SANs
- `certbot_dns_propagation_seconds`: DNS wait (default: 120)
- `certbot_dns_renewal_hooks`: commands to run post-renewal

## Example

```yaml
- hosts: macmini
  become: true
  vars:
    dns_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/dns.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.certbot_dns_deploy
      vars:
        certbot_dns_provider: gandi
        certbot_dns_domain: "home.xn--wersdrfer-47a.de"
        certbot_dns_email: "admin@wersdoerfer.de"
        certbot_dns_gandi_api_token: "{{ dns_secrets.gandi_api_key }}"
        certbot_dns_renewal_hooks:
          - "systemctl restart traefik"
          - "systemctl reload postfix@-"
          - "systemctl reload dovecot"
```

## Notes

- Certs end up at `/etc/letsencrypt/live/<domain>/`.
- Traefik can load the lineage via file provider; mail roles can point to the same paths.
- Traefik does not notice Certbot rotating targets outside its watched dynamic
  configuration directory. Always use an unmasked `systemctl restart traefik`
  hook so it loads the new certificate; a service reload is insufficient. The
  restart briefly interrupts proxied connections.
- The role installs one Bash deploy hook at `certbot_dns_renewal_hook_path`.
  Every configured item runs in an isolated fail-fast block, all items are
  attempted, and the script returns non-zero if any item fails. Use one item per
  independent consumer; shell variables, exported values, and working-directory
  changes do not carry between items. On multi-lineage hosts, an item may inspect
  `${RENEWED_LINEAGE:-}` and `exit 0` from its isolated block when it does not
  consume the renewed lineage. The empty default is intentional, so deployments
  must explicitly name their consumers. A role update does not migrate a
  downstream inventory's effective hook list; update it in the same rollout.
- Combine prerequisite or shared-state commands in one multi-line item so that
  block stays fail-fast. On Ubuntu's multi-instance Postfix packaging, reload
  `postfix@-`; the `postfix.service` meta unit may return success without
  reloading the active instance.
- Certbot does not retry a failed deploy hook once the renewed certificate is
  current. Some directory-hook runners log the failure without failing the
  overall renewal, so inspect the journal and Let's Encrypt log for
  `renewal hook item` or `returned error code` rather than relying only on the
  unit result; the hook diagnostic includes the renewed lineage. Then run
  `RENEWED_LINEAGE=/etc/letsencrypt/live/<cert-name> /etc/letsencrypt/renewal-hooks/deploy/reload-services.sh`
  (using the configured `certbot_dns_renewal_hook_path`; the shown path is its
  default) or manually restart or reload each consumer that did not load the new
  certificate.
- Store the API key in secrets (`secrets/prod/dns.yml`); do not commit.***
