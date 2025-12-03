# Certbot DNS Deploy

Role to obtain and renew wildcard/apex TLS certificates via Certbot using DNS-01 (Gandi LiveDNS).

- Installs certbot + dns-gandi plugin
- Renders provider credentials (Gandi LiveDNS API key)
- Requests a single lineage with apex + wildcard SANs
- Configures renewal hook to reload dependent services
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
          - "systemctl reload postfix || true"
          - "systemctl reload dovecot || true"
          - "systemctl reload traefik || true"
```

## Notes

- Certs end up at `/etc/letsencrypt/live/<domain>/`.
- Traefik can load the lineage via file provider; mail roles can point to the same paths.
- Store the API key in secrets (`secrets/prod/dns.yml`); do not commit.***
