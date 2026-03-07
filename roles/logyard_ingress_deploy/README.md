# logyard_ingress_deploy

Expose the Logyard Loki API through Traefik on an internal-only route.

This role intentionally does not create a public anonymous log-write endpoint.

## Behavior

- HTTPS host route for `logyard.home...`
- the bare root path `/` redirects to the Grafana Logyard landing dashboard
- requests are accepted only from configured LAN/Tailscale IP ranges
- HTTP requests redirect to HTTPS
- backend stays local on `127.0.0.1`

## Required Variables

```yaml
logyard_ingress_enabled: true
logyard_ingress_host: "logyard.home.xn--wersdrfer-47a.de"
logyard_ingress_backend_url: "http://127.0.0.1:3101"
logyard_ingress_root_redirect_url: "https://grafana.home.xn--wersdrfer-47a.de/d/logyard-home/logyard-overview"
```

## Validation

```bash
curl -sk https://logyard.home.xn--wersdrfer-47a.de/ -o /dev/null -D -
curl -sk https://logyard.home.xn--wersdrfer-47a.de/ready
sed -n '1,200p' /etc/traefik/dynamic/logyard.yml
```
