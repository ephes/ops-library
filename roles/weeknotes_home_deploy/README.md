# weeknotes_home_deploy

Deploys the `weeknotes.home` Django service from the `daybook` repository.

The role provisions a PostgreSQL database/user, syncs or checks out the daybook
source tree, installs the `weeknotes-home` uv dependency group, runs Django
migrations and static collection, installs a systemd gunicorn service, renders a
Traefik route, and verifies `/healthz`.

## Requirements

- Ubuntu/Debian target with systemd.
- PostgreSQL provisioned through the included `postgres_install` role tasks.
- Traefik when `weeknotes_home_traefik_enabled` is true.
- Real secrets supplied by the private control repo; this role's public defaults
  intentionally use `CHANGEME` placeholders and fail validation.

## Example

```yaml
- role: local.ops_library.weeknotes_home_deploy
  vars:
    weeknotes_home_deploy_method: rsync
    weeknotes_home_source_path: /Users/jochen/projects/daybook
    weeknotes_home_django_secret_key: "{{ service_secrets.django_secret_key }}"
    weeknotes_home_postgres_password: "{{ service_secrets.postgres_password }}"
    weeknotes_home_api_token: "{{ service_secrets.api_token }}"
    weeknotes_home_traefik_host: weeknotes.home.wersdoerfer.de
    weeknotes_home_basic_auth_user: "{{ traefik_secrets.basic_auth_user }}"
    weeknotes_home_basic_auth_password: "{{ traefik_secrets.basic_auth_password }}"
    weeknotes_home_cast_base_url: https://wersdoerfer.de
```

## Key Variables

- `weeknotes_home_deploy_method`: `rsync` for local/controller deploys or `git`
  for a clean checkout.
- `weeknotes_home_source_path`: controller checkout used in `rsync` mode.
- `weeknotes_home_git_repo`, `weeknotes_home_git_version`: source used in `git`
  mode.
- `weeknotes_home_django_secret_key`: required secret.
- `weeknotes_home_postgres_password`: required database user password.
- `weeknotes_home_api_token`: required owner-managed URL-safe bearer token
  (32-256 characters) protecting the open-comment and fold APIs. The same secret must
  be supplied to the Studio Daybook reconciler; it is never a browser-session
  credential.
- `weeknotes_home_cast_base_url`: optional public django-cast origin used to
  render edit and preview links for delivered drafts.
- `weeknotes_home_traefik_host`: hostname routed to the service.
- `weeknotes_home_basic_auth_enabled`: defaults to `true`; enables the required
  trusted/external dual-router boundary.
- `weeknotes_home_basic_auth_user`, `weeknotes_home_basic_auth_password`: shared
  Traefik front-door credentials supplied by the private control repo. The role
  generates a bcrypt hash with `htpasswd` under `no_log`.
- `weeknotes_home_basic_auth_password_hash`: optional precomputed bcrypt hash;
  when set, `htpasswd` and the plaintext password are not required.
- `weeknotes_home_internal_ip_ranges`: RFC1918 and Tailnet source ranges that
  use the higher-priority router without Basic Auth.
- `weeknotes_home_app_port`: local gunicorn port, default `10062`.

## Traefik Security Boundary

With the safe default (`weeknotes_home_basic_auth_enabled: true`), the generated
HTTPS configuration has two routers:

- priority `120`: `Host(...) && ClientIP(...)` for trusted LAN/Tailnet clients,
  preserving unattended Studio access to the bearer-protected machine APIs;
- priority `100`: `Host(...)` for every other source, with Basic Auth before
  the existing headers, gzip, TLS, and backend service behavior.

The Basic `Authorization` header is removed before proxying. The open-comment
and fold APIs retain their independent bearer checks; unattended API clients
must use the trusted router, which forwards their Bearer header unchanged. The
external router reserves that header for Basic Auth and is intended for browser
UI access. The HTTP router only performs a permanent HTTPS redirect via
Traefik's `noop@internal` service and never forwards request data to Django.

Disabling Basic Auth removes the source split and is only appropriate when an
equivalent external boundary exists and the exception is documented by the
private deployment. Trusted ranges must contain only private or explicitly
trusted networks; never add public ISP prefixes.

When the shared credential changes, the private control repo must either
redeploy this role or include its Traefik task in the shared credential rotation
workflow so the derived bcrypt hash is refreshed.

## Backup and Monitoring

This deploy role intentionally does not create backup or monitoring jobs. Wire
the deployed PostgreSQL database into Echoport and add a Nyxmon `/healthz` check
from the private ops-control repo, where service inventory, secrets, and backup
topology live.
