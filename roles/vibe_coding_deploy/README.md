# Vibe Coding Deploy Role

Set up a dedicated interactive coding user with persistent tmux sessions, fish shell, chezmoi-managed dotfiles, Node.js, and Claude Code. Designed for running AI coding agents on a remote Linux server.

## Features

- Creates a locked user (no sudo, SSH key-only) with home on a custom path (e.g. encrypted volume).
- Configures SSH `authorized_keys` and hardens sshd with a `Match User` block.
- Runs `shell_basics_deploy` for CLI tools (fish, tmux, fzf, ripgrep, zoxide, etc.) with `manage_fish_config: false` so chezmoi owns the fish config.
- Rsyncs chezmoi source from local machine and applies dotfiles (optional).
- Deploys API keys to `~/.config/fish/conf.d/secrets.fish` (role-managed, outside chezmoi).
- Installs Node.js LTS via NodeSource apt repo (pinned to major version).
- Installs Claude Code per-user via npm (user-owned prefix allows auto-updates).
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

# chezmoi dotfiles source dir (rsynced to target; empty to skip)
vibe_coding_chezmoi_source_dir: ""

# Environment variables deployed to fish conf.d/secrets.fish
vibe_coding_fish_env: {}
#   ANTHROPIC_API_KEY: "sk-ant-..."

# Extra packages passed through to shell_basics_deploy
vibe_coding_shell_basics_extra_packages:
  - zoxide

# Node.js (NodeSource LTS)
vibe_coding_install_node: true
vibe_coding_node_major_version: "22"

# Claude Code
vibe_coding_install_claude_code: true

# zellij (alongside tmux)
vibe_coding_zellij_install: true

# SSH hardening (Match User block in sshd_config)
vibe_coding_sshd_hardening: true
```

## Example Playbook

```yaml
- name: Deploy vibe coding environment
  hosts: macmini
  become: true
  vars:
    secrets: "{{ lookup('community.sops.sops', 'secrets/prod/vibe-coding.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.vibe_coding_deploy
      vars:
        vibe_coding_user_home: "/mnt/cryptdata/vibe"
        vibe_coding_ssh_authorized_keys:
          - "ssh-ed25519 AAAA... jochen@machine"
        vibe_coding_chezmoi_source_dir: "~/.local/share/chezmoi"
        vibe_coding_fish_env:
          ANTHROPIC_API_KEY: "{{ secrets.anthropic_api_key }}"
```

## Security

- **No sudo** — supplementary groups are stripped on each run (`groups: []`, `append: false`), so even pre-existing users in the `sudo` group have it removed.
- **Locked password** — SSH key-only authentication (`password: "!"`, `password_lock: true`).
- **No persistent GitHub keys** — existing `~/.ssh/id_*` private keys are removed on each run. Only `authorized_keys` remains.
- **SSH key required** — the role fails early if `vibe_coding_ssh_authorized_keys` is empty, preventing an unreachable locked account.
- **sshd Match block** enforces `PasswordAuthentication no`, `AllowAgentForwarding yes` (for `ta` workflow), `X11Forwarding no`, `AllowTcpForwarding no`.

## Task Order

1. Create group and user
2. Configure `authorized_keys`
3. Run `shell_basics_deploy` (fish config disabled)
4. Initialize/update chezmoi
5. Deploy secrets to `~/.config/fish/conf.d/secrets.fish`
6. Ensure `~/projects` directory
7. Install Node.js via NodeSource
8. Install coding tools via npm (per-user prefix)
9. Install zellij
10. Harden sshd for the user

## Notes

- The user's home directory must be on an existing mount (e.g. `/mnt/cryptdata`).
- Chezmoi source is rsynced from local machine; `chezmoi init --apply` runs on each deploy.
- Node.js is pinned to a major version via NodeSource (e.g. `22`); minor updates come via apt.
- Intended for Ubuntu targets. MIT licensed.
