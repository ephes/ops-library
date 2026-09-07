# static_site_deploy

Deploy a generated static website from the Ansible controller to a dedicated,
read-only service on a Linux host. The role syncs an explicitly selected source
directory, serves it on loopback with a hardened systemd-managed Python HTTP
server, and can publish it through an existing Traefik file-provider setup.

This role is intended for small generated archives such as benchmark reports.
It does not build the site, accept uploads, or expose the source directory
directly from the controller.

## Requirements

- A target with systemd, Python 3, and rsync.
- `ansible.posix` on the controller.
- An existing Traefik service watching the configured dynamic directory when
  `static_site_traefik_enabled` is true.
- Passwordless `sudo` and `rsync` for the remote connection user. Content sync
  invokes `sudo -n rsync` so it fails instead of prompting when privilege
  escalation is unavailable.
- A controller-side source directory whose absolute path uses only `A-Za-z0-9_./-`
  (no spaces or non-ASCII characters), containing every
  `static_site_required_files` entry as a regular file. Recursively, including
  hidden entries, the source may contain only regular files and directories;
  symbolic links, sockets, FIFOs, devices, and other entry kinds are rejected.

## Example

```yaml
- name: Publish generated documentation
  hosts: staging
  become: true
  roles:
    - role: local.ops_library.static_site_deploy
      vars:
        static_site_service_name: project-docs
        static_site_source_path: /srv/build/project-docs
        static_site_host: docs.staging.example.com
        static_site_port: 10061
        static_site_healthcheck_contains: Project documentation
```

The role binds the content server to `127.0.0.1`. Public traffic reaches it only
through the generated Traefik route. HTTP is redirected to HTTPS, directory
listing is disabled, connections time out after 10 seconds, and the service is
limited to 128 tasks and 256 MiB of memory. Public verification uses normal
certificate validation. Shared parent directories remain owned by root:root;
only the document root uses the service group.

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `static_site_service_name` | `static-site` | systemd, user, and Traefik object prefix. |
| `static_site_user` | service name | Dedicated system account. |
| `static_site_group` | service user | Dedicated system group. |
| `static_site_source_path` | `""` | Required absolute controller-side generated site directory. |
| `static_site_path` | `/srv/static-sites/<service>` | Remote document root. |
| `static_site_required_files` | `index.html`, `report.md`, `snapshot.json` | Regular files required before sync. |
| `static_site_restrict_to_required_files` | `false` | Reject nested directories or files outside the required-file allowlist. |
| `static_site_rsync_delete` | `true` | Remove remote content absent from the selected source. |
| `static_site_python_path` | `/usr/bin/python3` | Target Python interpreter. |
| `static_site_server_path` | `/usr/local/libexec/<service>-httpd.py` | Managed static server. |
| `static_site_bind_host` | `127.0.0.1` | IPv4 loopback bind address; every other value is rejected. |
| `static_site_port` | `10061` | Unprivileged loopback port. |
| `static_site_healthcheck_contains` | `""` | Optional text required in the local index response. |
| `static_site_systemd_unit_name` | service name | Managed systemd unit name. |
| `static_site_systemd_unit_path` | `/etc/systemd/system/<unit>.service` | Managed unit file path. |
| `static_site_traefik_enabled` | `true` | Render a Traefik file-provider config. |
| `static_site_host` | `static.example.com` | Public host; the placeholder is rejected. |
| `static_site_traefik_entrypoints` | `[web-secure]` | HTTPS entrypoints. |
| `static_site_traefik_http_entrypoint` | `web` | Plain-HTTP entrypoint used only for HTTPS redirection; it must differ from every HTTPS entrypoint. |
| `static_site_traefik_cert_resolver` | `""` | Optional named resolver; empty uses entrypoint defaults. |
| `static_site_traefik_config_path` | `/etc/traefik/dynamic/<service>.yml` | Dynamic configuration path. |
| `static_site_verify_public` | `false` | Verify the public HTTPS route after deployment. |
| `static_site_public_healthcheck_retries` | `20` | Public verification attempts. |
| `static_site_public_healthcheck_delay` | `3` | Seconds between public verification attempts. |

## Deployment and recovery

Re-run the role with the same source path to publish an updated snapshot. The
sync is idempotent and the content service does not need a restart when files
change.

If a publication is bad, regenerate or select the previous static output and
run the role again. The role owns only its service user, document root, server
script, systemd unit, and Traefik file. It does not remove unrelated services or
Traefik configuration.
