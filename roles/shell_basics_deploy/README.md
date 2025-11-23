# Shell Basics Deploy Role

Install a curated set of command line tools, switch the default shell to fish, and keep chezmoi up to date from upstream.

## Features

- Installs modern CLI defaults: `fish`, `eza`, `fd-find` (with `fd` symlink), `ripgrep`, `bat` (`batcat` symlink), `fzf`, `tmux`, `tealdeer`, `btop`, `bmon`, `sysstat` (`iostat`/`mpstat`), `iotop`, and common utilities.
- Fetches the latest chezmoi release via the official installer (no pinned, outdated `.deb`).
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
shell_basics_extra_packages: []     # Optional additions
shell_basics_apt_cache_valid_time: 3600

# Shell + editor management
shell_basics_switch_shell: true
shell_basics_manage_fish_config: true
shell_basics_fish_extra_config: []     # Extra lines appended in the managed fish block
shell_basics_set_default_editor: true
shell_basics_default_editor_path: /usr/bin/vim.basic

# chezmoi install (upstream installer)
shell_basics_manage_chezmoi: true
shell_basics_chezmoi_version: latest
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
- Chezmoi is installed from https://get.chezmoi.io using the latest release unless `shell_basics_chezmoi_version` is pinned.
- Fish config is managed via a dedicated block; existing content outside that block is left intact.
- Intended for Debian/Ubuntu targets (uses `apt`). MIT licensed.
