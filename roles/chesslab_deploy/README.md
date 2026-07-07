# chesslab_deploy

Deploys the Chesslab trainer as a standard granian-backed WSGI service behind
Traefik.

The role expects an existing SQLite database at `chesslab_db_path`. Source is
synced from the controller with rsync, dependencies are installed with `uv sync`,
and the service is started as `chesslab.service`.

Required production variables:

- `chesslab_source_path`
- `chesslab_users`, a list of app login users with `username`, `password`,
  and `owner` or `lichess_username`
- `chesslab_session_secret`
- `chesslab_traefik_host`
- `chesslab_basic_auth_password` when Traefik basic auth is enabled

When `chesslab_users` is configured, the role writes it to
`CHESSLAB_USERS_JSON`; the app then scopes due cards and reviews to the logged
in user's configured Lichess owner. The legacy `chesslab_login_user` and
`chesslab_login_password` variables remain available only as a single-user
fallback.

The deployed WSGI target is `chesslab.webapp:application`.
