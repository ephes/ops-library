# Minecraft Java Deploy Role

Deploy a Minecraft Java Edition server with RCON support, automated backups, and systemd service management.

This role supports two runtime modes:

1. `vanilla` (default)
2. `forge` (for modded servers)

## Requirements

- Ubuntu/Debian target system
- ansible-core 2.20+
- `community.general` collection (UFW module)
- Outbound internet on target host for Forge installer mode (Mojang + Maven mirrors)

## Mode Matrix

| Capability | `vanilla` | `forge` |
|---|---|---|
| Runtime entrypoint | `java -jar server.jar nogui` | Managed wrapper `start-forge.sh` (`exec java ...`) |
| Required artifact config | `minecraft_java_server_jar_*` | `minecraft_java_forge_*` |
| Mods management | No | Yes (`minecraft_java_mods*`) |
| Backup archive extras | World + base files | World + base files + `mods/` + `config/` |
| Default startup timeout | 60s | 300s |

## Required Variables

Always required:

```yaml
minecraft_java_eula_agreed: "true"
minecraft_java_rcon_password: "..."
```

Required in `vanilla` mode:

```yaml
minecraft_java_loader_mode: vanilla
minecraft_java_server_jar_url: "https://..."
minecraft_java_server_jar_sha256: "..."
```

Required in `forge` mode:

```yaml
minecraft_java_loader_mode: forge
minecraft_java_forge_version: "1.20.1-47.4.0"
minecraft_java_forge_installer_url: "https://..."
minecraft_java_forge_installer_sha256: "..."  # preferred
# or fallback:
# minecraft_java_forge_installer_sha1: "..."
```

## Key Variables

Core mode/safety:

- `minecraft_java_loader_mode`: `vanilla` or `forge`
- `minecraft_java_allow_mode_switch_same_world`: default `false`
- `minecraft_java_startup_timeout`: defaults to `60` (vanilla) or `300` (forge)

Forge runtime:

- `minecraft_java_forge_installer_path`
- `minecraft_java_forge_unix_args_path`
- `minecraft_java_forge_user_jvm_args_path`
- `minecraft_java_forge_wrapper_script_path`
- `minecraft_java_forge_version_marker_path`
- `minecraft_java_forge_checksum_marker_path`

Mods:

- `minecraft_java_mods_enabled`: default `false`
- `minecraft_java_mods_prune_unmanaged`: default `false`
- `minecraft_java_mods`: list of mod definitions

Mod entry schema:

```yaml
minecraft_java_mods:
  - name: "example-mod"
    version: "1.2.3"  # optional metadata
    url: "https://example.org/mod.jar"
    sha256: "..."
    filename: "example-mod.jar"  # optional override
    enabled: true                # optional, default true
```

`enabled: false` means the jar is removed from `mods/` so it cannot load.

## Mode Switch Guardrail

The role tracks loader mode in `{{ minecraft_java_server_dir }}/.loader_mode`.

- Missing marker is treated as `vanilla` for backward compatibility.
- If loader mode changes and world name stays the same, deployment fails by default.
- Override only when intentional: `minecraft_java_allow_mode_switch_same_world: true`

This is to prevent accidental world downgrade/corruption when switching versions/loaders.

## JVM Args in Forge Mode

In `forge` mode, JVM args are managed in `user_jvm_args.txt`:

- `-Xms{{ minecraft_java_memory_min }}`
- `-Xmx{{ minecraft_java_memory_max }}`
- `minecraft_java_extra_args`

The service uses a managed wrapper script that performs `exec java ...` directly with Forge `unix_args.txt`, so systemd tracks the Java PID cleanly.

## Backup Behavior

Tier 1 cron backup:

- Uses `systemctl is-active` to verify service state (mode-agnostic)
- Uses RCON `save-off` / `save-all` / `save-on`
- `vanilla`: archives world + core server files
- `forge`: archives world + core files + `mods/` + `config/`

Tier 2 backup/restore roles continue to work unchanged.

## Migration Guide

Vanilla -> Forge:

1. Create a backup first.
2. Set `minecraft_java_loader_mode: forge`.
3. Set Forge installer/version/checksum variables.
4. Prefer a new `minecraft_java_world_name` for safety.
5. Optionally enable and configure `minecraft_java_mods*`.
6. Deploy and verify startup logs and RCON.

Forge -> Vanilla:

1. Create a backup.
2. Set `minecraft_java_loader_mode: vanilla`.
3. Set `minecraft_java_server_jar_url` + `minecraft_java_server_jar_sha256`.
4. Deploy and verify startup.

Rollback note: switching Forge -> vanilla does not automatically delete Forge artifacts (`mods/`, `config/`, Forge libraries/run files). This is expected; clean up manually if desired.

## World Version Warning

Do not reuse a higher-version world when switching to an older Minecraft/Forge stack.

If current world was opened on a newer version, use a fresh world name or a compatible restore point.

## Example Playbook Snippets

Vanilla:

```yaml
- role: local.ops_library.minecraft_java_deploy
  vars:
    minecraft_java_loader_mode: vanilla
    minecraft_java_eula_agreed: "true"
    minecraft_java_server_jar_url: "{{ minecraft_secrets.server_jar_url }}"
    minecraft_java_server_jar_sha256: "{{ minecraft_secrets.server_jar_sha256 }}"
    minecraft_java_rcon_password: "{{ minecraft_secrets.rcon_password }}"
```

Forge:

```yaml
- role: local.ops_library.minecraft_java_deploy
  vars:
    minecraft_java_loader_mode: forge
    minecraft_java_eula_agreed: "true"
    minecraft_java_forge_version: "{{ minecraft_secrets.forge_version }}"
    minecraft_java_forge_installer_url: "{{ minecraft_secrets.forge_installer_url }}"
    minecraft_java_forge_installer_sha256: "{{ minecraft_secrets.forge_installer_sha256 }}"
    minecraft_java_rcon_password: "{{ minecraft_secrets.rcon_password }}"
    minecraft_java_mods_enabled: true
    minecraft_java_mods: "{{ minecraft_secrets.mods }}"
```

## Service Operations

```bash
systemctl status minecraft-java
journalctl -u minecraft-java -f
mcrcon -H 127.0.0.1 -P 25575 -p "PASSWORD" -t
```

## Security Notes

- RCON port (25575) is blocked externally via UFW
- Game port (25565) allowed only from configured networks
- Service runs as dedicated `minecraft` user
- Systemd hardening enabled (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem`)

## License

MIT
