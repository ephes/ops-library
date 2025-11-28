# Minecraft Java Deploy Role

Deploy a Minecraft Java Edition server with RCON support, automated backups, and systemd service management.

## Description

This role deploys a vanilla Minecraft Java Edition server with:
- OpenJDK 21 runtime with optimized JVM flags
- RCON enabled for backup coordination and remote management
- Two-tier backup system (hourly cron + on-demand via backup role)
- Systemd service with security hardening
- UFW firewall rules (game port allowed, RCON blocked externally)
- mcrcon tool for RCON communication

## Requirements

- Ubuntu/Debian-based target system
- ansible-core 2.15+
- Required collections:
  - `community.general` (for UFW module)

## Role Variables

### Required Variables

These variables MUST be set when using this role:

```yaml
minecraft_java_eula_agreed: "true"           # Must accept Minecraft EULA
minecraft_java_server_jar_url: ""            # Download URL from minecraft.net or mcversions.net
minecraft_java_server_jar_sha256: ""         # SHA256 checksum of server.jar
minecraft_java_rcon_password: ""             # Password for RCON (used by backup scripts)
```

### Common Configuration

```yaml
# Server settings
minecraft_java_port: 25565
minecraft_java_max_players: 20
minecraft_java_difficulty: normal            # peaceful, easy, normal, hard
minecraft_java_gamemode: survival            # survival, creative, adventure, spectator
minecraft_java_motd: "A Minecraft Server"
minecraft_java_pvp: true

# Memory allocation
minecraft_java_memory_min: 2G
minecraft_java_memory_max: 4G

# Whitelist (optional)
minecraft_java_whitelist_enabled: false
minecraft_java_whitelist_players: []
minecraft_java_ops: []
```

### All Variables

See `defaults/main.yml` for the complete list of variables with descriptions.

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Deploy Minecraft Java Server
  hosts: gameserver
  become: true
  vars:
    minecraft_secrets: "{{ lookup('community.sops.sops', 'secrets/minecraft.yml') | from_yaml }}"

  roles:
    - role: local.ops_library.minecraft_java_deploy
      vars:
        minecraft_java_eula_agreed: "true"
        minecraft_java_server_jar_url: "{{ minecraft_secrets.server_jar_url }}"
        minecraft_java_server_jar_sha256: "{{ minecraft_secrets.server_jar_sha256 }}"
        minecraft_java_rcon_password: "{{ minecraft_secrets.rcon_password }}"
        minecraft_java_max_players: 10
        minecraft_java_motd: "My Minecraft Server"
```

## Backup System

### Tier 1: Operational Backups (Cron)

- Runs hourly via cron
- Stores backups in `/home/minecraft/backups/`
- Uses RCON to coordinate saves (save-off, save-all, archive, save-on)
- Retains 24 hours of backups by default
- Good for quick recovery from in-game accidents

### Tier 2: Disaster Recovery (Backup Role)

- On-demand via `just backup minecraft_java`
- Stores archives in `/opt/backups/minecraft-java/`
- Synced to local machine for off-site storage
- Used for full server recovery after reinstall

## Service Management

```bash
# Check status
systemctl status minecraft-java

# View logs
journalctl -u minecraft-java -f

# RCON console
mcrcon -H 127.0.0.1 -P 25575 -p "PASSWORD" -t
```

## Security

- RCON port (25575) is blocked externally via UFW
- Game port (25565) allowed only from configured networks
- Service runs as dedicated `minecraft` user
- Systemd security hardening (NoNewPrivileges, PrivateTmp, ProtectSystem)

## License

MIT

## Author

ops-library contributors
