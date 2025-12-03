# Minecraft Java Remove Role

Remove a Minecraft Java Edition server installation.

## Description

This role completely removes the Minecraft Java server:
- Stops and disables the systemd service
- Removes the service file
- Removes the cron backup job
- Removes the minecraft user and home directory
- Removes UFW firewall rules

**Note:** Backups in `/opt/backups/minecraft-java/` are NOT removed automatically.

## Requirements

- ansible-core 2.20+
- Required collections:
  - `community.general` (for UFW module)

## Role Variables

### Required Variables

```yaml
minecraft_java_confirm_removal: true    # Safety confirmation (MUST be true)
```

### Optional Variables

```yaml
minecraft_java_user: minecraft
minecraft_java_group: minecraft
minecraft_java_home: /home/minecraft
minecraft_java_service_name: minecraft-java
minecraft_java_port: 25565
minecraft_java_rcon_port: 25575
minecraft_java_firewall_allowed_networks:
  - "192.168.0.0/16"
  - "10.0.0.0/8"
  - "100.64.0.0/10"
```

## Dependencies

None.

## Example Playbook

```yaml
---
- name: Remove Minecraft Java Server
  hosts: gameserver
  become: true

  roles:
    - role: local.ops_library.minecraft_java_remove
      # NOTE: minecraft_java_confirm_removal must be passed via -e flag
      # Do NOT hardcode to true here - safety guard
```

Run with:
```bash
ansible-playbook remove.yml -e minecraft_java_confirm_removal=true
```

## Usage with ops-control

```bash
just remove-one minecraft_java
```

## What Gets Removed

- `/etc/systemd/system/minecraft-java.service`
- `/home/minecraft/` (entire directory including world data)
- `minecraft` user and group
- Cron job for hourly backups
- UFW rules for ports 25565 and 25575

## What Is NOT Removed

- `/opt/backups/minecraft-java/` - Delete manually if not needed
- mcrcon binary (`/usr/local/bin/mcrcon`) - May be used by other services
- OpenJDK - May be used by other applications

## License

MIT

## Author

ops-library contributors
