# UV Install Role

Install and manage the Astral uv package manager.

## Features

- Installs uv into a configurable system path (default `/usr/local/bin`)
- Supports explicit owner/group for cross-platform compatibility (`root:wheel` on macOS)
- Optionally creates system-wide symlinks for compatibility
- Supports updating existing installations
- Verifies installation and basic functionality

## Requirements

- tar and gzip on the managed host

## Role Variables

```yaml
# Pinned version; update the matching uv_checksum map together.
uv_version: "0.13.5"

# Installation directory
uv_install_dir: "/usr/local/bin"

# File ownership for installed binaries
uv_install_owner: "root"
uv_install_group: "{{ 'wheel' if ansible_facts.os_family == 'Darwin' else 'root' }}"

# System-wide symlink location
uv_symlink_dir: "/usr/local/bin"

# Whether to create system-wide symlinks
uv_create_symlinks: false

# Whether to update if already installed
uv_update_existing: true
```

## Example Playbook

```yaml
- hosts: servers
  roles:
    - role: local.ops_library.uv_install
      vars:
        uv_version: "0.13.5"
        uv_create_symlinks: true
```

## Check mode

The role supports `ansible-playbook --check` with its defaults; no
`-e uv_update_existing=false` is needed. The read-only `uv --version` probe
also runs in check mode, so a host that already has the pinned version reports
no change. When an install or update is due, check mode reports it as one
changed task and downloads, extracts and installs nothing. The Molecule
scenario runs the role with `--check` for an up-to-date host, a pending update
and a host without uv.

## Usage in Deployment Roles

UV is typically used as a dependency in service deployment roles:

```yaml
# In your custom deployment role's meta/main.yml
dependencies:
  - role: local.ops_library.uv_install

# Or in a playbook
- name: Deploy Python service
  hosts: servers
  roles:
    - role: local.ops_library.uv_install
    - role: local.ops_library.myservice_deploy
```

## License

MIT

## Verified release downloads

Release archives install `uv` and `uvx` in `uv_install_dir` with `uv_install_owner`/`uv_install_group` and mode 0755. Extraction uses the system tar (GNU or BSD). Supported targets are Linux glibc and macOS, on x86_64 and ARM64. `uv_update_existing` and `uv_force_reinstall` retain their behavior. With updates enabled, an absent, unreadable or different installed version is replaced. Automatic self-update and `uv_version: latest` are no longer supported.

Pinned defaults (checksum map keys identify the release architecture/target):

| Variable | Default |
| --- | --- |
| `uv_version` | `0.13.5` |
| `uv_checksum` | See the release-target table below. |

| Release target | SHA-256 |
| --- | --- |
| x86_64-unknown-linux-gnu | `f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f` |
| aarch64-unknown-linux-gnu | `4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403` |
| x86_64-apple-darwin | `b0f52b0e3945b4107d89024ea38e625683011fbfc05a0d98f9fa2d6dcee28c66` |
| aarch64-apple-darwin | `743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.

The default uv pins in `homeassistant_deploy`, `open_webui_venv_deploy` and
`metube_shared` must also be updated when bumping the shared uv pin. The
regression gate checks that their default versions match these checksums.
