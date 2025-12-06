# Certbot DNS Restore Role

Restore Certbot state (`/etc/letsencrypt`) from an archive and validate with a dry-run renewal.

## Description

Extracts a previously archived Certbot directory, fixes permissions on the credentials file, and optionally runs `certbot renew --dry-run` to verify the restored state.

## Role Variables

```yaml
certbot_dns_restore_archive: ""          # Path to backup archive (required)
certbot_dns_restore_dest: "/"            # Destination root for extraction
certbot_dns_dir: "/etc/letsencrypt"      # Certbot directory
certbot_dns_credentials_file: "/etc/letsencrypt/dns-credentials.ini"
certbot_dns_restore_run_dry_renew: true  # Run certbot renew --dry-run after restore
```

## Example Playbook

```yaml
- hosts: macmini
  become: true
  vars:
    certbot_dns_restore_archive: "/opt/backups/certbot-dns/manual-20251202T2200.tar.gz"
  roles:
    - role: local.ops_library.certbot_dns_restore
```

## Notes

- Archive is expected to contain `/etc/letsencrypt`. Ensure permissions are kept private (credentials file 0600).
- Dry-run renewal can be disabled with `certbot_dns_restore_run_dry_renew: false`.
