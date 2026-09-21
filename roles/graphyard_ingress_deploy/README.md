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

- The deploy helper extraction keeps the public role entrypoint unchanged
  while moving the duplicated Traefik config and basic-auth hashing plumbing
  into `local.ops_library.webapp_deploy_internal`. Graphyard-specific ingress
  validation and Graphyard env-file reconciliation stay in this role.
- The external routers use Traefik basic auth with `removeHeader: true`.
  This intentionally strips the `Authorization` header before forwarding to backends.
  Keep ingest producers on direct/local Graphyard ingest URLs (`http://127.0.0.1:8051/v1/metrics`) rather than through these public Traefik routers.
- HTTP routers include a dynamic `redirect-to-https` middleware as defense in depth.
- This role relies on Traefik file-provider hot reload (`[providers.file].watch = true`) for dynamic config updates.

## Optional private inventory receiver

Set `graphyard_ingress_inventory_enabled: true` only for a Graphyard version
providing host-bound inventory writer authentication. The default is `false`.
The exact `/v1/inventory` path gets a higher-priority HTTPS router for all sources:
only `graphyard_ingress_internal_ip_ranges` pass its IP allowlist; other sources
receive 403, including callers with valid UI basic auth. Allowed producers keep
their bearer Authorization header for Graphyard to verify. This is not a public
basic-auth bypass for any other path, nor does IP allowlisting replace writer auth.

The route limits requests to 8 MiB (413 beyond that), buffers at most 1 MiB per
body in memory before using disk, permits two in-flight requests shared by all writers targeting the same request host and limits
each source IP to six requests per minute with burst four (429 on excess).
No proxy retries are configured; the producer owns idempotent retries. UI, status,
metrics and Grafana routes are unchanged. Body/rate policies use Traefik's
[buffering](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/buffering/)
and [rate limit](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/ratelimit/)
middlewares. This role does not enroll hosts, issue credentials or run collectors.

Before receiving reports, deploy the Graphyard inventory migrations, configure
`graphyard_sqlite_synchronous: FULL` in the core role, and verify backup/restore.
Check anonymous writer rejection, authenticated delivery, 413/429 enforcement,
private reader access and existing metrics health on the live endpoint. Setting
the inventory flag back to false removes only the dedicated ingress policy;
it does not disable the application's endpoint behind the existing generic
routers. To disable ingestion, also revoke writers/disable inventory hosts.

The application registers only the exact ingest path `/v1/inventory`. A trailing
slash returns 404; `/v1/inventory/status` is a separate authenticated reader API.
Keep those distinctions when changing application routes. In-flight grouping is
explicitly by request host, as documented by
[Traefik InFlightReq](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/inflightreq/).
