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
uv_version: "0.13.4"

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
        uv_version: "0.13.4"
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
| `uv_version` | `0.13.4` |
| `uv_checksum` | x86_64-unknown-linux-gnu: `sha256:2b428396f12572d4429cf210ca234dd599a33b3af0958a4d5ed569d63e3f344f`<br>aarch64-unknown-linux-gnu: `sha256:1ae72b4718729e2ccc4f1ae2c6d1e531ca8467800e0546e9130b3886023a60ab`<br>x86_64-apple-darwin: `sha256:7be2dcd316122f4b3e5a0a7889f6248266c14425374e105ff7dc9779184603a6`<br>aarch64-apple-darwin: `sha256:e0b1d4743ce64c55d9f0f4a444afa6b81125680070ee04e853fcd0f6c1ebf8f1` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.

The default uv pins in `homeassistant_deploy`, `open_webui_venv_deploy` and
`metube_shared` must also be updated when bumping the shared uv pin. The
regression gate checks that their default versions match these checksums.
