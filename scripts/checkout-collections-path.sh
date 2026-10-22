#!/usr/bin/env bash
# Print an ANSIBLE_COLLECTIONS_PATH under which this checkout is the
# local.ops_library collection, for local playbook tests whose role code uses
# include_role with the collection name (for example
# local.ops_library.webapp_deploy_internal).
#
# The directory lives outside the checkout (a symlink inside it would make
# tools that walk the tree recurse into the repository again) and is keyed by
# the checkout path, so parallel checkouts never resolve each other's roles.
set -euo pipefail

repo_root=$(cd -- "$(dirname "$0")/.." && pwd -P)
if command -v shasum >/dev/null 2>&1; then
    digest=$(printf '%s' "$repo_root" | shasum -a 256)
else
    digest=$(printf '%s' "$repo_root" | sha256sum)
fi
root="${XDG_CACHE_HOME:-$HOME/.cache}/ops-library-collections/${digest:0:12}"
mkdir -p "$root/ansible_collections/local"
ln -sfn "$repo_root" "$root/ansible_collections/local/ops_library"
printf '%s\n' "$root"
