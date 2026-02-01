# ssh_guard_deploy

Harden SSH access against brute-force noise by enabling fail2ban and applying a small sshd drop-in. This is designed to be safe for key-based access and to reduce MaxStartups lockouts.

## What it does

- Installs and enables `fail2ban` with an `sshd` jail.
- Writes `/etc/ssh/sshd_config.d/99-ssh-guard.conf` to set `PerSourceMaxStartups` (and optional `MaxAuthTries` / `LoginGraceTime`).
- Validates `sshd -t` and reloads the SSH service.

## Requirements

- Debian/Ubuntu with systemd and OpenSSH.
- Root privileges on the target host.

## Role Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ssh_guard_fail2ban_enabled` | `true` | Install and configure fail2ban. |
| `ssh_guard_fail2ban_package` | `fail2ban` | Package name. |
| `ssh_guard_fail2ban_service_name` | `fail2ban` | Service name. |
| `ssh_guard_fail2ban_jail_name` | `sshd` | Jail to configure. |
| `ssh_guard_fail2ban_backend` | `systemd` | Fail2ban backend. |
| `ssh_guard_fail2ban_filter` | `sshd` | Fail2ban filter name. |
| `ssh_guard_fail2ban_port` | `ssh` | SSH port name or number. |
| `ssh_guard_fail2ban_maxretry` | `5` | Retry threshold. |
| `ssh_guard_fail2ban_findtime` | `10m` | Time window. |
| `ssh_guard_fail2ban_bantime` | `1h` | Ban duration. |
| `ssh_guard_fail2ban_ignoreip` | `127.0.0.1/8 ::1 100.64.0.0/10` | Whitelist trusted IPs/CIDRs (includes Tailscale CGNAT range). |
| `ssh_guard_sshd_dropin_enabled` | `true` | Write sshd drop-in config. |
| `ssh_guard_sshd_dropin_path` | `/etc/ssh/sshd_config.d/99-ssh-guard.conf` | Drop-in path. |
| `ssh_guard_sshd_service_name` | `ssh` | SSH service name. |
| `ssh_guard_per_source_max_startups` | `5` | Per-source SSH handshake limit. Set empty to omit. |
| `ssh_guard_max_auth_tries` | `""` | Optional `MaxAuthTries` value. |
| `ssh_guard_login_grace_time` | `""` | Optional `LoginGraceTime` value. |

## Example

```yaml
- name: Harden SSH on staging
  hosts: staging
  become: true
  roles:
    - role: local.ops_library.ssh_guard_deploy
      vars:
        ssh_guard_per_source_max_startups: "3"
        ssh_guard_fail2ban_bantime: "1h"
```

## Notes

- The role uses an sshd drop-in (Debian-compatible). It validates `sshd -t` before reload.
- Consider raising `ssh_guard_per_source_max_startups` if you run many parallel Ansible forks from a single control host.
- Fail2ban configuration is stored under `/etc/fail2ban/jail.d/ssh-guard.local`.
