# ollama_remove

Remove Ollama on macOS by unloading the launchd service and optionally cleaning up data, logs, users, and the Homebrew package.

## Description

This role stops/unloads the Ollama launchd service, removes the plist, and optionally deletes model data/logs,
removes the service user/group, and uninstalls the Homebrew package. Defaults are safe and preserve data.

## Requirements

- macOS target (Darwin)
- Homebrew installed and available at `/opt/homebrew/bin/brew` or `/usr/local/bin/brew`
  (or set `ollama_brew_bin` explicitly) when removing the package
- Ansible 2.15+
- `community.general` collection (already required by this collection)

## Role Variables

### Common Configuration (matches `ollama_install`)

```yaml
ollama_launchd_label: "com.ollama.ollama"
ollama_launchd_plist_path: "/Library/LaunchDaemons/com.ollama.ollama.plist"
ollama_service_user: "ollama"
ollama_service_group: "ollama"
ollama_service_home: "/usr/local/var/ollama"
ollama_models_dir: "/usr/local/var/ollama/models"
ollama_log_dir: "/usr/local/var/ollama/logs"
```

### Removal Options

```yaml
ollama_remove_data: false          # Remove model data directory
ollama_remove_logs: false          # Remove log directory
ollama_remove_user: false          # Remove service user/group
ollama_remove_brew_package: false  # Uninstall Homebrew package
```

### Homebrew Settings (used when removing the package)

```yaml
ollama_brew_user: ""   # Required when Ansible connects as root
ollama_brew_bin: ""    # Auto-detect if empty
ollama_brew_package: "ollama"
```

For a complete list of variables, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

### Basic Removal (service + plist only)

```yaml
- name: Remove Ollama launchd service
  hosts: macs
  become: true
  roles:
    - role: local.ops_library.ollama_remove
```

### Full Cleanup (models/logs/user + Homebrew package)

```yaml
- name: Remove Ollama with data cleanup
  hosts: macs
  become: true
  vars:
    ollama_remove_data: true
    ollama_remove_logs: true
    ollama_remove_user: true
    ollama_remove_brew_package: true
    ollama_brew_user: "jochen"  # Required when running as root
  roles:
    - role: local.ops_library.ollama_remove
```

## Usage Notes

- Run as root to unload the system launchd service.
- Homebrew does not allow root execution. When `ollama_remove_brew_package: true` and Ansible connects as root,
  set `ollama_brew_user` (and optionally `ollama_brew_bin`).

## Tags

None.

## Testing

```bash
cd /path/to/ops-library
just test-role ollama_remove
```

## Changelog

- **1.0.0** (2026-01-17): Initial release
- See [CHANGELOG.md](../../CHANGELOG.md) for full history

## License

MIT

## Author Information

ops-library
