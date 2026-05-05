# zellij_ingress_deploy

Drop a Traefik dynamic config on the edge host that issues a temporary redirect
from a friendly host name (e.g. `zellij.home.xn--wersdrfer-47a.de`) to a fixed
target URL — typically a Tailscale Serve endpoint that fronts a `zellij web`
instance bound to `127.0.0.1` on a backend host.

## Why a Redirect-Only Ingress?

Zellij refuses to bind to non-loopback addresses without a TLS certificate, so
its web client must stay on `127.0.0.1`. Tailscale Serve exposes that loopback
port over the tailnet with HTTPS (no cert management). This role lets the
homepage / dashboard tile use a uniform `*.home...` URL that redirects to the
real Tailscale Serve URL.

## What This Role Manages

- A Traefik dynamic config file (`/etc/traefik/dynamic/zellij.yml` by default)
- One HTTPS router and one HTTP router on the configured host name
- A `redirectRegex` middleware sending all requests to the target URL
  (uses Traefik's built-in `noop@internal` service since the middleware
  short-circuits before any backend is hit)

## Important Defaults

```yaml
zellij_ingress_traefik_enabled: true
zellij_ingress_traefik_host: ""
zellij_ingress_redirect_target: ""
zellij_ingress_traefik_entrypoints:
  - web-secure
zellij_ingress_traefik_cert_resolver: ""
zellij_ingress_traefik_config_path: "/etc/traefik/dynamic/zellij.yml"
zellij_ingress_allowed_ip_ranges:
  - "127.0.0.1/32"
  - "::1/128"
  - "100.64.0.0/10"
  - "fd7a:115c:a1e0::/48"
```

## Example

```yaml
- name: Expose Zellij over a friendly redirect URL
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.zellij_ingress_deploy
      vars:
        zellij_ingress_traefik_host: "zellij.home.xn--wersdrfer-47a.de"
        zellij_ingress_redirect_target: "https://studio.tailde2ec.ts.net/"
```

## Backend Setup (Out of Scope for This Role)

On the backend host (e.g. `studio`):

```bash
zellij web --start                                          # binds 127.0.0.1:8082
tailscale serve --bg --https=443 http://127.0.0.1:8082      # exposes via tailnet HTTPS
```

`tailscale serve` persists across reboots once configured.

## Notes

- This role assumes Traefik already watches `/etc/traefik/dynamic/`.
- Leave `zellij_ingress_traefik_cert_resolver` empty when the wildcard
  file-provider certificate already covers the host.
- The IP allow-list is consistent with the other `*_ingress_deploy` roles —
  external clients receive a 404 rather than the redirect.
