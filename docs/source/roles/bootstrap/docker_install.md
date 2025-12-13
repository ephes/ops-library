# Docker Install Role

Bootstrap role for installing Docker Engine and Docker Compose v2 on Ubuntu.

## Capabilities

- Adds the official Docker apt repository
- Installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, and `docker-compose-plugin`
- Enables and starts the `docker` systemd unit (configurable)
- Optional `/etc/docker/daemon.json` management
- Optional user provisioning into the `docker` group

## Usage

```yaml
- hosts: ubuntu_hosts
  become: true
  roles:
    - role: local.ops_library.docker_install
```

Add users to the docker group:

```yaml
- hosts: ubuntu_hosts
  become: true
  roles:
    - role: local.ops_library.docker_install
      vars:
        docker_install_users:
          - jochen
```

## Key Variables

- `docker_install_enable_service`: enable the systemd unit (default: `true`)
- `docker_install_start_service`: start the systemd unit (default: `true`)
- `docker_install_configure_daemon`: write `/etc/docker/daemon.json` (default: `false`)
- `docker_install_daemon_config`: dict to render into `daemon.json` (default: `{}`)
- `docker_install_verify_docker_info`: run `docker info` (default: `true`)

Refer to `roles/docker_install/defaults/main.yml` for the complete list.
