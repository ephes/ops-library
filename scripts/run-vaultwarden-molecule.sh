#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname "$0")/.."

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export DOCKER_HOST="${DOCKER_HOST:-unix:///Users/jochen/.colima/default/docker.sock}"
export ANSIBLE_ALLOW_BROKEN_CONDITIONALS=1
export ANSIBLE_COLLECTIONS_PATH="${ANSIBLE_COLLECTIONS_PATH:-$HOME/.ansible/collections:/usr/share/ansible/collections:$PWD}"

roles=(
  vaultwarden_deploy
  vaultwarden_backup
  vaultwarden_restore
  vaultwarden_remove
)

for role in "${roles[@]}"; do
  echo "==> Running molecule for ${role}"
  (cd "roles/${role}" && molecule test -s default)
done
