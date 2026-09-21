# macos_ssh_tunnel

Manage one macOS user LaunchAgent that forwards a loopback TCP port through SSH
to an HTTPS service. Deployment installs it **stopped**. Explicit start enables
reconnection and login startup; stop disables both. No scheduler or GUI application
is launched. Updating the role stops the tunnel; run start after deployment.

## Requirements

- macOS, a logged-in Aqua user, OpenSSH, and Python 3.11+ for the controller.
- An unattended SSH identity and an already trusted relay host key. This role
  does not provision either; `ssh_forwarding_identity` can manage the identity.
- The SSH server must allow forwarding to the specified destination.
- Local hostname routing and certificate trust are managed by the caller.
  A proxy setting alone may not cover every application transport.

## Configuration

All defaults are in `defaults/main.yml`.

| Variable | Default / purpose |
| --- | --- |
| `macos_ssh_tunnel_state` | `present`; `absent` stops and removes managed files |
| `macos_ssh_tunnel_home` | Current user's home; deployment must run as that user |
| `macos_ssh_tunnel_label` | `org.example.ssh-tunnel`; unique launchd label |
| `macos_ssh_tunnel_directory` | `~/Library/Application Support/SSH Tunnel` |
| `macos_ssh_tunnel_plist` | `~/Library/LaunchAgents/<label>.plist` |
| `macos_ssh_tunnel_log_directory` | `~/Library/Logs/SSH Tunnel` |
| `macos_ssh_tunnel_host` | Required SSH relay hostname or IPv4 address |
| `macos_ssh_tunnel_user` | Required SSH username |
| `macos_ssh_tunnel_identity` | `~/.ssh/tunnel_ed25519`; no agent fallback |
| `macos_ssh_tunnel_known_hosts` | `~/.ssh/known_hosts`; strict host checking |
| `macos_ssh_tunnel_target` | Required upstream HTTPS hostname |
| `macos_ssh_tunnel_target_port` | `443` |
| `macos_ssh_tunnel_local_port` | `18443`; unprivileged, IPv4 loopback only |
| `macos_ssh_tunnel_ignore_ssl_errors` | `false`; explicit opt-out only |
| `macos_ssh_tunnel_ca_file` | Empty, using Python's default CA trust |
| `macos_ssh_tunnel_health_path` | `/`; unauthenticated read-only endpoint |
| `macos_ssh_tunnel_health_status` | `200`; exact expected HTTP status |
| `macos_ssh_tunnel_python` | `/opt/homebrew/bin/python3`; displayed command |

## Example

```yaml
- hosts: localhost
  connection: local
  gather_facts: true
  roles:
    - role: local.ops_library.macos_ssh_tunnel
      vars:
        macos_ssh_tunnel_host: relay.example.org
        macos_ssh_tunnel_user: operator
        macos_ssh_tunnel_target: backend.example.org
```

## Operations

```bash
app_dir="$HOME/Library/Application Support/SSH Tunnel"
python3 "$app_dir/tunnel_control.py" --config "$app_dir/config.json" start
python3 "$app_dir/tunnel_control.py" --config "$app_dir/config.json" status
python3 "$app_dir/tunnel_control.py" --config "$app_dir/config.json" check
python3 "$app_dir/tunnel_control.py" --config "$app_dir/config.json" stop
```

`restart` stops then starts. Lifecycle commands serialize on `config.lock`.
`start` rejects an occupied port without adopting or killing that process.
`status` reports launchd state and the SSH log path; a loaded job is not proof
of a working connection. `check` verifies hostname routing to `127.0.0.1`, TLS,
and the configured HTTP status. It connects directly to loopback, bypassing proxy
environment variables, while retaining upstream SNI and HTTP Host.
`check --transport-only` skips hostname routing, useful before administrative DNS
setup. Neither mode checks application credentials. Explicit SSL bypass is printed.

SSH keepalives detect a lost relay connection; launchd retries exited SSH processes
with a 60-second throttle. A reachable relay with an unavailable downstream service
can leave SSH running, so use `check` after VPN or network changes.

`state: absent` removes only named managed files. Logs, parent directories, SSH
identity, remote authorization, and hostname overrides remain caller-owned. Stop
other lifecycle operations during deployment/removal. This role is an infrastructure
helper with no application data requiring a backup/restore role.

Run `just test-macos-ssh-tunnel` for the controller regression suite using the
project Python environment. The HTTPS tests also require an `openssl` CLI in PATH
to create a short-lived test certificate.
