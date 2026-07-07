# chesslab_deploy

Deploys the Chesslab trainer as a standard granian-backed WSGI service behind
Traefik. The served application is the Django app at
`chesslab.djangoapp.wsgi:application`.

The role expects an existing SQLite database at `chesslab_db_path`. Source is
synced from the controller with rsync, dependencies are installed with `uv sync`,
and the service is started as `chesslab.service`.

Required production variables:

- `chesslab_source_path`
- `chesslab_django_secret_key`
- `chesslab_users`, a list of Django app users with `username`, `password`,
  and `owner` or `lichess_username`
- `chesslab_traefik_host`
- `chesslab_basic_auth_password` when Traefik basic auth is enabled

The role runs Django migrations against `chesslab_db_path` and then calls
`chesslab django ensure_admin` for each configured user. Passwords are supplied
through `CHESSLAB_ADMIN_PASSWORD`, not as command-line arguments. The app scopes
due cards and reviews to the logged-in user's `accounts.Profile.lichess_username`.

Traefik basic auth may still be enabled as an edge middleware, but it is no
longer the Chesslab application login.
