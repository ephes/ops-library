# Docker Install Role

An ops-library bootstrap role for installing Docker Engine and Docker Compose v2 (as the official Docker CLI plugin) on Ubuntu.

## Features

- Installs Docker Engine (`docker-ce`) from the official Docker apt repository
- Installs Compose v2 via `docker-compose-plugin` (exposes `docker compose ...`)
- Optional daemon configuration (`/etc/docker/daemon.json`)
- Optional user provisioning for the `docker` group
- Basic verification steps (CLI + optional daemon connectivity)

## Requirements

- Ansible `2.15` or newer
- Target OS: Ubuntu 20.04+ (systemd)

## Variables

See `defaults/main.yml` for the full list. Key options:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `docker_install_enable_service` | `true` | Enable docker systemd unit |
| `docker_install_start_service` | `true` | Start docker systemd unit |
| `docker_install_users` | `[]` | Users to add to the `docker` group |
| `docker_install_configure_daemon` | `false` | Write `/etc/docker/daemon.json` |
| `docker_install_daemon_config` | `{}` | Dict rendered as JSON into `daemon.json` |
| `docker_install_verify_docker_info` | `true` | Run `docker info` (requires daemon running) |

## Examples

### Install Docker + Compose v2 with defaults

```yaml
- hosts: ubuntu_hosts
  become: true
  roles:
    - role: local.ops_library.docker_install
```

### Add a user to the docker group

```yaml
- hosts: ubuntu_hosts
  become: true
  roles:
    - role: local.ops_library.docker_install
      vars:
        docker_install_users:
          - jochen
```

> Note: group changes require the user to re-login to pick up the new group membership.

### Configure Docker daemon (example)

```yaml
- hosts: ubuntu_hosts
  become: true
  roles:
    - role: local.ops_library.docker_install
      vars:
        docker_install_configure_daemon: true
        docker_install_daemon_config:
          log-driver: json-file
          log-opts:
            max-size: "10m"
            max-file: "3"
```

## Verification

1. `docker --version`
2. `docker compose version`
3. `systemctl status docker` (when `docker_install_start_service: true`)
4. `docker info` (when `docker_install_verify_docker_info: true`)
