# graphyard_ingress_deploy

Expose an existing Graphyard stack through Traefik with the standard protected-service policy:

- Tailscale/LAN source IPs are allowed directly (no Traefik basic auth).
- Public source IPs require Traefik HTTP basic auth.

The role configures both endpoints:

- Graphyard web API/UI (for example `graphyard.home.xn--wersdrfer-47a.de`)
- Grafana UI used by the Graphyard stack (for example `grafana.home.xn--wersdrfer-47a.de`)

## What This Role Manages

- Traefik dynamic config file with dual routers for both hosts.
- Shared basic auth middleware (external routers only).
- Optional update of `/etc/graphyard/graphyard.env`:
  - `DJANGO_ALLOWED_HOSTS`
  - `DJANGO_CSRF_TRUSTED_ORIGINS`
  - `DJANGO_ADMIN_URL` (optional; only when set)
  - `GRAFANA_BASE_URL`
- Service restart handlers:
  - restart `graphyard-web`
  - restart `graphyard-agent`

## Important Defaults

```yaml
graphyard_ingress_enabled: false
graphyard_ingress_graphyard_host: "graphyard.example.com"
graphyard_ingress_grafana_host: "grafana.example.com"
graphyard_ingress_graphyard_backend_url: "http://127.0.0.1:8051"
graphyard_ingress_grafana_backend_url: "http://127.0.0.1:3300"
graphyard_ingress_traefik_cert_resolver: ""   # set, for example, "letsencrypt" when wildcard file certs do not cover the host

graphyard_ingress_basic_auth_enabled: true
graphyard_ingress_basic_auth_user: "admin"
# graphyard_ingress_basic_auth_password: "<required when auth enabled>"
graphyard_ingress_django_admin_url: ""      # optional; example "hidden_admin/" to move admin off /admin/
```

## Example

```yaml
- name: Expose Graphyard + Grafana behind Traefik
  hosts: macmini
  become: true
  vars:
    traefik_secrets: "{{ lookup('community.sops.sops', playbook_dir + '/../secrets/prod/traefik.yml') | from_yaml }}"
  roles:
    - role: local.ops_library.graphyard_ingress_deploy
      vars:
        graphyard_ingress_enabled: true
        graphyard_ingress_graphyard_host: "graphyard.home.xn--wersdrfer-47a.de"
        graphyard_ingress_grafana_host: "grafana.home.xn--wersdrfer-47a.de"
        graphyard_ingress_traefik_cert_resolver: "letsencrypt"
        graphyard_ingress_basic_auth_user: "{{ traefik_secrets.basic_auth_user | default('admin') }}"
        graphyard_ingress_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"
        graphyard_ingress_django_allowed_hosts:
          - "127.0.0.1"
          - "localhost"
          - "macmini.tailde2ec.ts.net"
          - "graphyard.home.xn--wersdrfer-47a.de"
        graphyard_ingress_django_csrf_trusted_origins:
          - "http://127.0.0.1"
          - "http://localhost"
          - "https://graphyard.home.xn--wersdrfer-47a.de"
        graphyard_ingress_django_admin_url: "hidden_admin/"
        graphyard_ingress_grafana_public_url: "https://grafana.home.xn--wersdrfer-47a.de"
```

## Notes

- The external routers use Traefik basic auth with `removeHeader: true`.
  This intentionally strips the `Authorization` header before forwarding to backends.
  Keep ingest producers on direct/local Graphyard ingest URLs (`http://127.0.0.1:8051/v1/metrics`) rather than through these public Traefik routers.
- HTTP routers include a dynamic `redirect-to-https` middleware as defense in depth.
- This role relies on Traefik file-provider hot reload (`[providers.file].watch = true`) for dynamic config updates.
