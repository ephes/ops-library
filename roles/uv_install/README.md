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
uv_version: "0.13.0"

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
        uv_version: "0.13.0"
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
| `uv_version` | `0.13.0` |
| `uv_checksum` | x86_64-unknown-linux-gnu: `sha256:1468ebd5a5541121837c5a2817b9972ba6090fa6caa3d142620850a47fb75154`<br>aarch64-unknown-linux-gnu: `sha256:3ccfb6af6e242433eb552f7d9676abd5412c6595c497e990d9c8cb7b5bd4d2c3`<br>x86_64-apple-darwin: `sha256:5f44dcbde809b632f47c36fadb241cb4d6f9af71d0c8f172b5d2026d3dde742c`<br>aarch64-apple-darwin: `sha256:a9c1b29002cf3c83f07fa9cd8a887a3be0107d90e23189721221e7257db8e3d6` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.

The default uv pins in `homeassistant_deploy`, `open_webui_venv_deploy` and
`metube_shared` must also be updated when bumping the shared uv pin. The
regression gate checks that their default versions match these checksums.
