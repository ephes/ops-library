# voxhelm_ingress_deploy

Expose an existing Voxhelm deployment through Traefik with the same private HTTPS pattern used for OpsGate:

- The Django service runs on the backend host (for example `studio`).
- Traefik terminates TLS on the edge host (for example `macmini`).
- Only trusted local/Tailscale source IPs are routed.

## What This Role Manages

- Traefik dynamic config file for `https://{{ voxhelm_ingress_traefik_host }}`
- HTTP-to-HTTPS redirect for the same host
- Standard security/compression middlewares
- A high-priority `/v1/internal` edge decision: blocked by default, or routed
  only when a separate worker-internal allowlist is deliberately configured

## Important Defaults

```yaml
voxhelm_ingress_traefik_enabled: true
voxhelm_ingress_traefik_host: ""
voxhelm_ingress_backend_url: ""
voxhelm_ingress_traefik_config_path: "/etc/traefik/dynamic/voxhelm.yml"
voxhelm_ingress_traefik_cert_resolver: ""
voxhelm_ingress_allowed_ip_ranges:
  - "127.0.0.1/32"
  - "::1/128"
  - "100.64.0.0/10"
  - "fd7a:115c:a1e0::/48"
voxhelm_ingress_internal_api_enabled: false
voxhelm_ingress_internal_api_allowed_ip_ranges: []
voxhelm_ingress_internal_api_block_ip_ranges:
  - "255.255.255.255/32"
```

## Example

```yaml
- name: Expose Voxhelm over private HTTPS
  hosts: macmini
  become: true
  roles:
    - role: local.ops_library.voxhelm_ingress_deploy
      vars:
        voxhelm_ingress_backend_url: "http://voxhelm-backend.example.test:8787"
        voxhelm_ingress_traefik_host: "voxhelm.home.xn--wersdrfer-47a.de"
```

## Notes

- This role assumes Traefik already watches `/etc/traefik/dynamic/`.
- Leave `voxhelm_ingress_traefik_cert_resolver` empty when the wildcard file-provider certificate already covers the host.
- Voxhelm keeps bearer-token auth at the application layer; this role only handles private HTTPS routing.
- `/v1/internal` is not exposed through the normal producer/operator route.
  If remote workers must reach Voxhelm through this Traefik host, set
  `voxhelm_ingress_internal_api_enabled: true` and provide a narrow
  `voxhelm_ingress_internal_api_allowed_ip_ranges` list for those worker hosts.
  Workers should use the HTTPS URL directly; the plain-HTTP redirect route is
  still scoped to the normal producer/operator allowlist.
