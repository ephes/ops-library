# Vibe Coding Deploy Role

Set up a dedicated interactive coding user with persistent tmux sessions, fish shell, chezmoi-managed dotfiles, Node.js, and Claude Code. Designed for running AI coding agents on a remote Linux server.

## Features

- Creates a locked user (no sudo, SSH key-only) with home on a custom path (e.g. encrypted volume).
- Configures SSH `authorized_keys` and hardens sshd with a `Match User` block.
- Fixes SSH agent forwarding inside tmux/zellij by deploying `~/.ssh/rc` (creates a stable `~/.ssh/auth_sock` symlink on each login) and a fish `conf.d` snippet that points `SSH_AUTH_SOCK` at the symlink.
- Runs `shell_basics_deploy` for CLI tools (fish, tmux, fzf, ripgrep, zoxide, etc.) with `manage_fish_config: false` so chezmoi owns the fish config.
- Installs GitHub CLI (`gh`) and can manage durable GitHub auth in `~/.config/gh/hosts.yml` for non-interactive release automation.
- Clones dotfiles repo via SSH agent forwarding and applies with chezmoi (preferred), or rsyncs chezmoi source from local machine (legacy fallback).
- Deploys API keys to `~/.config/fish/conf.d/secrets.fish` (role-managed, outside chezmoi).
- Installs Node.js LTS via NodeSource apt repo (pinned to major version).
- Installs Neovim from GitHub releases (pinned version; apt is too old for LazyVim).
- Installs lazygit from GitHub releases (required by LazyVim `<leader>gg`).
- Installs Rust toolchain via rustup with rust-analyzer (needed by LazyVim rust extra).
- Installs Claude Code and other AI coding tools per-user via npm (user-owned prefix allows auto-updates).
- Cleans up conflicting system-wide npm packages automatically.
- Installs zellij alongside tmux as a first-class multiplexer option.

## Role Variables

```yaml
# User and group
vibe_coding_user: "vibe"
vibe_coding_group: "vibe"
vibe_coding_user_home: "/mnt/cryptdata/vibe"
vibe_coding_shell: "/usr/bin/fish"

# Projects directory
vibe_coding_projects_dir: "{{ vibe_coding_user_home }}/projects"

# SSH authorized keys (list of public key strings)
vibe_coding_ssh_authorized_keys: []

# chezmoi dotfiles git repo (cloned via SSH agent forwarding; preferred)
vibe_coding_dotfiles_repo: ""  # e.g. "git@github.com:user/dotfiles.git"

# chezmoi dotfiles source dir (rsynced to target; legacy fallback)
vibe_coding_chezmoi_source_dir: ""

# Environment variables deployed to fish conf.d/secrets.fish
vibe_coding_fish_env: {}
#   ANTHROPIC_API_KEY: "sk-ant-..."

# Extra packages passed through to shell_basics_deploy
vibe_coding_shell_basics_extra_packages:
  - gh
  - zoxide

# Node.js (NodeSource LTS)
vibe_coding_install_node: true
vibe_coding_node_major_version: "22"

# Neovim (from GitHub releases)
vibe_coding_neovim_version: "0.12.5"

# lazygit (from GitHub releases)
vibe_coding_lazygit_version: "0.65.1"

# Rust toolchain (rustup + rust-analyzer)
vibe_coding_install_rust: true

# Per-user npm prefix (user-owned, allows auto-updates)
vibe_coding_npm_prefix: "{{ vibe_coding_user_home }}/.npm-global"

# AI coding tools installed via npm (per-user)
vibe_coding_npm_tools:
  - "@anthropic-ai/claude-code"
  - "@openai/codex"
  - "opencode-ai"
  - "@mariozechner/pi-coding-agent"

# zellij (alongside tmux)
vibe_coding_zellij_install: true

# Optional GitHub CLI auth (writes ~/.config/gh/hosts.yml)
vibe_coding_github_cli_auth_enabled: false
vibe_coding_github_username: ""
vibe_coding_github_token: ""

# SSH hardening (Match User block in sshd_config)
vibe_coding_sshd_hardening: true
```

## Example Playbook

```yaml
- name: Deploy vibe coding environment
  hosts: macmini
  become: true
  vars:
    ansible_ssh_extra_args: "-o ForwardAgent=yes"
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/vibe-coding.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.vibe_coding_deploy
      vars:
        vibe_coding_user_home: "/mnt/cryptdata/vibe"
        vibe_coding_ssh_authorized_keys:
          - "ssh-ed25519 AAAA... jochen@machine"
        vibe_coding_dotfiles_repo: "git@github.com:user/dotfiles.git"
        vibe_coding_fish_env:
          ANTHROPIC_API_KEY: "{{ secrets.anthropic_api_key }}"
        vibe_coding_github_cli_auth_enabled: true
        vibe_coding_github_username: "{{ secrets.github_username }}"
        vibe_coding_github_token: "{{ secrets.github_token }}"
```

## Security

- **No sudo** — supplementary groups are stripped on each run (`groups: []`, `append: false`), so even pre-existing users in the `sudo` group have it removed.
- **Locked password** — SSH key-only authentication (`password: "!"`, `password_lock: true`).
- **No persistent GitHub keys** — existing `~/.ssh/id_*` private keys are removed on each run. Only `authorized_keys` remains.
- **Optional durable `gh` auth** — when enabled, the role writes `~/.config/gh/hosts.yml` with mode `0600` for GitHub CLI automation on Linux hosts without relying on shell-only environment variables.
- **SSH key required** — the role fails early if `vibe_coding_ssh_authorized_keys` is empty, preventing an unreachable locked account.
- **sshd Match block** enforces `PasswordAuthentication no`, `AllowAgentForwarding yes`, `PermitUserRC yes` (for agent forwarding inside multiplexers), `X11Forwarding no`, `AllowTcpForwarding no`.

## Task Order

1. Create group and user
2. Configure `authorized_keys`, deploy `~/.ssh/rc` and agent-forwarding fish snippet
3. Run `shell_basics_deploy` (fish config disabled)
4. Initialize/update chezmoi
5. Deploy secrets to `~/.config/fish/conf.d/secrets.fish`
6. Configure GitHub CLI auth in `~/.config/gh/hosts.yml` (optional)
7. Ensure `~/projects` directory
8. Install Node.js via NodeSource
9. Install Neovim from GitHub releases
10. Install lazygit from GitHub releases
11. Install Rust toolchain via rustup
12. Install coding tools via npm (per-user prefix, with system-wide cleanup)
13. Install zellij
14. Harden sshd for the user

## Notes

- The user's home directory must be on an existing mount (e.g. `/mnt/cryptdata`).
- When `vibe_coding_dotfiles_repo` is set, the repo is git-cloned to the target via SSH agent forwarding. The vibe user can then run `chezmoi update` or `git pull` independently. Requires `ansible_ssh_extra_args: "-o ForwardAgent=yes"` in the playbook.
- Legacy: when only `vibe_coding_chezmoi_source_dir` is set, chezmoi source is rsynced from local machine (no `.git` on target).
- Node.js is pinned to a major version via NodeSource (e.g. `22`); minor updates come via apt.
- Intended for Ubuntu targets. MIT licensed.

## Verified release downloads

Linux x86_64 and aarch64 are supported. Neovim and lazygit retain version-based installation guards; matching versions are left alone. Neovim stays under `/opt/nvim-linux-<arch>` with `/usr/local/bin/nvim` as a symlink; lazygit and zellij stay in `/usr/local/bin`, owned by root, mode 0755. Zellij and rustup retain installation-only guards: existing installations are left alone. Rustup-init is verified before running as `vibe_coding_user`, keeping its toolchain under that user’s home. Rustup toolchain/component downloads continue to use rustup’s upstream verification; the pin here covers the bootstrap binary. NodeSource’s existing repository signing-key download remains unverified because no vendor checksum was found; the regression helper exempts only its exact existing URL/task file. Apt package authentication and per-user npm installs are outside the release-binary checks.

Pinned defaults (checksum map keys identify the release architecture/target):

| Variable | Default |
| --- | --- |
| `vibe_coding_neovim_version` | `0.12.5` |
| `vibe_coding_lazygit_version` | `0.65.1` |
| `vibe_coding_rustup_version` | `1.29.1` |
| `vibe_coding_zellij_version` | `0.45.1` |
| `vibe_coding_lazygit_checksum` | x86_64: `sha256:02beacbcda0fa342e50ae3480ba8147307353af3fb28e1d5f790e02329c201a6`<br>arm64: `sha256:49abecdf6adf4f2dfdb11bf7b9bfada267ea523612ed809d1c6d87f6c04000a7` |
| `vibe_coding_neovim_checksum` | x86_64: `sha256:bce0f56eda1f1b1db6eee8f4133d7a38813ea07933837dd1777411ca384c6875`<br>arm64: `sha256:1aa5ca085249580ae0f91eb14f27ec0919773ff2d99a163d03f3d6c21ac29725` |
| `vibe_coding_zellij_checksum` | x86_64: `sha256:40bcc2e03f5d5ae8e054e39f676081fe12ab70871506996ba595834c3718eefc`<br>aarch64: `sha256:05f0802afadd53f8db9514e7cae53c9ae8432fed1b35b8294aa816ee3044a16b` |
| `vibe_coding_rustup_checksum` | x86_64: `sha256:dda7234360b7f578ca8b0ddcb80145646fa61a67c1720a5abc7051b35c9fcb71`<br>aarch64: `sha256:15f6e4ce9f583b929c996c91562bad6d4454f3281de858b02cdfdef615fac433` |

To update, bump the version and checksum together. Fetch the SHA-256 from the
project’s published checksum file or release-page asset digest over HTTPS,
and update the source URL comment beside the checksum in `defaults/main.yml`.
Never reuse the old checksum for a new version. Supply matching checksums for
every enabled architecture. Run `just test-root-downloads` before deploying.
