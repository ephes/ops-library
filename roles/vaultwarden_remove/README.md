# Vaultwarden Remove Role

Remove Vaultwarden password manager from a server.

## Quick Start

```yaml
- hosts: server
  roles:
    - role: local.ops_library.vaultwarden_remove
      vars:
        vaultwarden_confirm_removal: true
        vaultwarden_remove_data: false  # Keep data by default
```

## Safety

This role requires explicit confirmation to prevent accidental removal:

```yaml
vaultwarden_confirm_removal: true  # Required to proceed
```

## Role Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `vaultwarden_confirm_removal` | `false` | Must be `true` to proceed |
| `vaultwarden_remove_data` | `false` | Remove all data (database, attachments) |
| `vaultwarden_remove_config` | `true` | Remove configuration files |
| `vaultwarden_remove_repository` | `true` | Remove apt repository |
| `vaultwarden_remove_traefik` | `true` | Remove Traefik configuration |

## Data Handling

By default, data is **preserved** at `/var/lib/vaultwarden` to allow for recovery.

To remove all data:

```yaml
vaultwarden_remove_data: true
```

**Warning**: This creates a backup at `/root/vaultwarden-backup-*.tar.gz` before deletion, but this backup is NOT encrypted. Handle with care.

## What Gets Removed

1. Vaultwarden systemd service (stopped and disabled)
2. Vaultwarden packages (`vaultwarden`, `vaultwarden-web-vault`)
3. Systemd override configuration
4. Traefik dynamic configuration (optional)
5. Apt repository and GPG key (optional)
6. Configuration file `/etc/vaultwarden.env` (optional)
7. Data directory `/var/lib/vaultwarden` (optional, disabled by default)
8. Log directory `/var/log/vaultwarden` (only if removing data)
