# logyard_ingress_deploy

Expose the Logyard Loki push endpoint through Traefik on an internal-only route.

This role intentionally does not create a public anonymous log-write endpoint,
and it does not expose the Loki query API. Loki runs with `auth_enabled: false`,
so anything the route forwards is unauthenticated for every allowed client IP.

## Behavior

- HTTPS host route for `logyard.home...`
- the bare root path `/` redirects to the Grafana Logyard landing dashboard
- requests are accepted only from configured LAN/Tailscale IP ranges
- only the paths in `logyard_ingress_allowed_paths` are forwarded to Loki, each
  with its own methods; by default `POST /loki/api/v1/push` (Vector's `loki`
  sink) and `GET`/`HEAD /ready` (Vector's healthcheck and the validation curl)
- every other path on the host, including `/loki/api/v1/query`, `query_range`,
  `tail`, `labels`, `series` and `delete`, has no router and returns `404`
- HTTP requests redirect to HTTPS
- backend stays local on `127.0.0.1`

## Required Variables

```yaml
logyard_ingress_enabled: true
logyard_ingress_host: "logyard.home.xn--wersdrfer-47a.de"
logyard_ingress_backend_url: "http://127.0.0.1:3101"
logyard_ingress_root_redirect_url: "https://grafana.home.xn--wersdrfer-47a.de/d/logyard-home/logyard-overview"
```

## Optional Variables

```yaml
# Exact paths and HTTP methods forwarded to Loki (default shown).
logyard_ingress_allowed_paths:
  - path: "/loki/api/v1/push"
    methods: ["POST"]
  - path: "/ready"
    methods: ["GET", "HEAD"]
```

Paths are matched exactly (Traefik `Path`), must start with `/` and use only
URL-safe characters; methods must be upper case. Do not add query endpoints
here: there is no authentication in front of them.

## Who reads Loki

Nobody needs the query API through this route:

- Grafana uses the provisioned datasource from `logyard_deploy`, which points at
  `http://<logyard_loki_container_name>:<logyard_loki_http_port>` over the shared
  docker network (`access: proxy`, so browsers query through Grafana).
- The `logyard_deploy` health endpoint queries `http://127.0.0.1:3101` on the
  host.
- A producer on the Loki host itself (for example the macmini Vector) can push
  to `http://127.0.0.1:3101` directly.

For ad-hoc queries, use Grafana Explore, or run `logcli`/`curl` against
`127.0.0.1:3101` on the Loki host over SSH.

## Validation

```bash
curl -sk https://logyard.home.xn--wersdrfer-47a.de/ -o /dev/null -D -
curl -sk https://logyard.home.xn--wersdrfer-47a.de/ready
# expect 404: the query API is not routed
curl -sk -o /dev/null -w '%{http_code}\n' 'https://logyard.home.xn--wersdrfer-47a.de/loki/api/v1/labels'
sed -n '1,200p' /etc/traefik/dynamic/logyard.yml
```
