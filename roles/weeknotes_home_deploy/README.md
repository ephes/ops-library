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
    weeknotes_home_traefik_host: weeknotes.home.wersdoerfer.de
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
- `weeknotes_home_cast_base_url`: optional public django-cast origin used to
  render edit and preview links for delivered drafts.
- `weeknotes_home_traefik_host`: internal hostname routed to the service.
- `weeknotes_home_app_port`: local gunicorn port, default `10062`.

## Backup and Monitoring

This deploy role intentionally does not create backup or monitoring jobs. Wire
the deployed PostgreSQL database into Echoport and add a Nyxmon `/healthz` check
from the private ops-control repo, where service inventory, secrets, and backup
topology live.
