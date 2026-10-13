# Shell Basics Deploy Role

Install a curated set of command line tools, switch the default shell to fish, and keep chezmoi up to date from upstream.

The package and idempotence path is exercised on Debian 13 in Molecule.

## Features

- Installs modern CLI defaults: `fish`, `eza`, `fd-find` (with `fd` symlink), `ripgrep`, `bat` (`batcat` symlink), `fzf`, `tmux`, `tealdeer`, `just`, `btop`, `bmon`, `sysstat` (`iostat`/`mpstat`), `iotop`, and common utilities.
- Installs a pinned chezmoi release archive verified by SHA-256.
- Adds a managed block to `~/.config/fish/config.fish` using `fish_add_path` so existing user content is preserved; optional extra lines supported.
- Switches the target user's login shell to fish and sets the system `editor` alternative to `vim.basic`.
- All paths and user details are configurable.

## Role Variables

```yaml
# User and paths
shell_basics_user: root
shell_basics_user_home: ""          # Auto-detected when empty
shell_basics_shell_path: /usr/bin/fish

# Packages
shell_basics_packages:              # Core set
  - fish
  - bat
  - fzf
  - ripgrep
  - fd-find
  - eza
  - tmux
  - tree
  - tig
  - lsof
  - sudo
  - file
  - git
  - strace
  - psmisc
  - vim
  - btop
  - bmon
  - sysstat
  - iotop
  - tealdeer
  - just
shell_basics_extra_packages: []     # Optional additions
shell_basics_apt_cache_valid_time: 3600

# Shell + editor management
shell_basics_switch_shell: true
shell_basics_manage_fish_config: true
shell_basics_fish_extra_config: []     # Extra lines appended in the managed fish block
shell_basics_set_default_editor: true
shell_basics_default_editor_path: /usr/bin/vim.basic

# chezmoi install (verified release archive)
shell_basics_manage_chezmoi: true
shell_basics_chezmoi_version: "2.73.1"
shell_basics_chezmoi_install_dir: /usr/local/bin
shell_basics_chezmoi_bin_path: "{{ shell_basics_chezmoi_install_dir }}/chezmoi"
```

## Example Playbook

```yaml
- hosts: macmini
  become: true
  roles:
    - role: local.ops_library.shell_basics_deploy
      vars:
        shell_basics_user: root
        shell_basics_switch_shell: true
        shell_basics_extra_packages:
          - dnsutils
```

## Notes

- The role symlinks `~/.local/bin/bat` → `/usr/bin/batcat` and `~/.local/bin/fd` → `/usr/bin/fdfind` when present.
- Chezmoi is installed from a pinned GitHub release archive, verified before extraction.
- Fish config is managed via a dedicated block; existing content outside that block is left intact.
- Intended for Debian/Ubuntu targets (uses `apt`). MIT licensed.

## Verified release downloads

Verified Linux amd64/arm64 archives install only the chezmoi binary at `shell_basics_chezmoi_bin_path`, owned by root, mode 0755. A differing installed version is replaced; a matching version is left alone. `latest` is no longer supported.

Pinned defaults (checksum map keys identify the release architecture/target):

| Variable | Default |
| --- | --- |
| `shell_basics_chezmoi_version` | `2.73.1` |
| `shell_basics_chezmoi_checksum` | amd64: `sha256:a3f958acb7d0e5d53fa43c2eec9bc8ae3b4fba8bcbfdce29a8881ca3ffc20a53`<br>arm64: `sha256:e60275b27f505ae2086bfb87b144eacf7377a89803120f6bd933d1852a93b0c6` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.
