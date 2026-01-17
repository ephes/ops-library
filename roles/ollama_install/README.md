# ollama_install

Install and run Ollama on macOS using Homebrew and a managed launchd LaunchDaemon.

## Description

This role installs the Ollama CLI via Homebrew, creates a dedicated service user (optional),
manages the model/data directories, and renders a launchd plist to run `ollama serve`
as a background service on macOS.

## Requirements

- macOS target (Darwin)
- Homebrew installed and available at `/opt/homebrew/bin/brew` or `/usr/local/bin/brew`
  (or set `ollama_brew_bin` explicitly)
- Ansible 2.15+
- `community.general` collection (already required by this collection)

## Role Variables

### Required Variables

None.

### Common Configuration

```yaml
ollama_brew_bin: ""                # Auto-detect if empty
ollama_brew_update: false          # Set true to run brew update during install
ollama_launchd_label: "com.ollama.ollama"
ollama_launchd_command: "serve"
ollama_launchd_command_args: []
ollama_service_user: "ollama"
ollama_service_group: "ollama"
ollama_service_home: "/usr/local/var/ollama"
ollama_models_dir: "/usr/local/var/ollama/models"
ollama_log_dir: "/usr/local/var/ollama/logs"
ollama_env:
  OLLAMA_HOST: "127.0.0.1:11434"
  OLLAMA_MODELS: "{{ ollama_models_dir }}"
```

### User Management

```yaml
ollama_manage_user: true           # Create/manage the service user/group
ollama_service_uid: ""             # Optional UID override
ollama_service_gid: ""             # Optional GID override
```

### Advanced Configuration

```yaml
ollama_binary_path: ""             # Optional override for the Ollama binary path
ollama_launchd_plist_path: "/Library/LaunchDaemons/com.ollama.ollama.plist"
```

For a complete list of variables, see `defaults/main.yml`.

## Dependencies

None.

## Example Playbook

### Basic Usage

```yaml
- name: Install Ollama on macOS
  hosts: macs
  become: true
  roles:
    - role: local.ops_library.ollama_install
```

### Custom Model Directory + Environment

```yaml
- name: Install Ollama with custom paths
  hosts: macs
  become: true
  vars:
    ollama_models_dir: "/srv/ollama/models"
    ollama_service_home: "/srv/ollama"
    ollama_log_dir: "/srv/ollama/logs"
    ollama_env:
      OLLAMA_HOST: "0.0.0.0:11434"
      OLLAMA_MODELS: "/srv/ollama/models"
  roles:
    - role: local.ops_library.ollama_install
```

## Handlers

This role provides the following handlers:

- `Restart Ollama launchd service` - Reloads the launchd plist and restarts the Ollama service

## Tags

None.

## Testing

```bash
cd /path/to/ops-library
just test-role ollama_install
```

## Changelog

- **1.0.0** (2026-01-17): Initial release
- See [CHANGELOG.md](../../CHANGELOG.md) for full history

## License

MIT

## Author Information

ops-library
