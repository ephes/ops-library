# Minecraft Java Backup Role

Create disaster recovery backups of a Minecraft Java Edition server.

## Description

This role creates Tier 2 (disaster recovery) backups of the Minecraft server, including:
- World data
- Server configuration (server.properties)
- Player data (ops.json, whitelist.json, banned-*.json if present)

The backup process coordinates with the running server via RCON to ensure data consistency:
1. Disable auto-save (`save-off`)
2. Flush world to disk (`save-all`)
3. Create archive
4. Re-enable auto-save (`save-on`)

## Requirements

- Minecraft Java server deployed via `minecraft_java_deploy` role
- RCON enabled and accessible
- ansible-core 2.20+

## Role Variables

### Required Variables

```yaml
minecraft_java_rcon_password: ""    # RCON password (same as deploy)
```

### Optional Variables

```yaml
minecraft_java_backup_prefix: "manual"           # Prefix for backup filename
minecraft_java_backup_root: /opt/backups/minecraft-java
minecraft_java_backup_retention_count: 10        # Keep N most recent backups
```

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Backup Minecraft Java Server
  hosts: gameserver
  become: true
  vars:
    minecraft_secrets: "{{ lookup('community.sops.sops', 'secrets/minecraft.yml') | from_yaml }}"

  roles:
    - role: local.ops_library.minecraft_java_backup
      vars:
        minecraft_java_rcon_password: "{{ minecraft_secrets.rcon_password }}"
        minecraft_java_backup_prefix: "scheduled"
```

## Usage with ops-control

```bash
# Create backup
just backup minecraft_java

# List backups
just list-backups minecraft_java
```

## Backup Location

Backups are stored in `/opt/backups/minecraft-java/` with naming convention:
```
{prefix}-{timestamp}.tar.gz
```

## License

MIT

## Author

ops-library contributors
