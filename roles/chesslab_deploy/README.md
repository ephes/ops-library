# chesslab_deploy

Deploys the Chesslab trainer as a standard granian-backed WSGI service behind
Traefik.

The role expects an existing SQLite database at `chesslab_db_path`. Source is
synced from the controller with rsync, dependencies are installed with `uv sync`,
and the service is started as `chesslab.service`.

Required production variables:

- `chesslab_source_path`
- `chesslab_login_password`
- `chesslab_session_secret`
- `chesslab_traefik_host`
- `chesslab_basic_auth_password` when Traefik basic auth is enabled

The deployed WSGI target is `chesslab.webapp:application`.
