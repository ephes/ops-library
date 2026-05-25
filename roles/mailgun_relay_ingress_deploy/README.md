# mailgun_relay_ingress_deploy

Render a Traefik dynamic-config YAML for the mailgun-relay backend.

This role intentionally does NOT add basic auth at the edge: the relay
enforces its own HTTP Basic (Mailgun `api:<token>` scheme) per-token before
SMTP submission. Adding a second basic-auth layer at Traefik would break
Anymail clients.

## Role variables

| Variable | Default | Notes |
| --- | --- | --- |
| `mailgun_relay_ingress_enabled` | `false` | |
| `mailgun_relay_ingress_traefik_config_path` | `/etc/traefik/dynamic/mailgun-relay.yml` | |
| `mailgun_relay_ingress_traefik_cert_resolver` | `""` | empty -> use file-provider certs |
| `mailgun_relay_ingress_host` | `mailgun.home.xn--wersdrfer-47a.de` | punycode |
| `mailgun_relay_ingress_backend_url` | `http://127.0.0.1:8085` | local FastAPI |
| `mailgun_relay_ingress_max_request_body_bytes` | `26_214_400` | matches service body cap |

The Traefik file provider hot-reloads the dynamic config; no Traefik restart
is required.
