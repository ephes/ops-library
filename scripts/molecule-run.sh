#!/usr/bin/env bash
# Run one Molecule command for one role scenario with run-scoped resources.
#
# Usage: scripts/molecule-run.sh <role> <scenario> <molecule-command> [args...]
#
# Every molecule.yml names its platforms "<name>-${MOLECULE_RUN_ID:-local}", so
# the Docker container names (and inventory host names) come from
# MOLECULE_RUN_ID. This wrapper picks that ID, a matching Molecule ephemeral
# directory (state file, generated inventory) and ANSIBLE_HOME (where Molecule
# installs this checkout as a collection) so parallel runs from different
# checkouts never share a container, Molecule state or collection install:
#
# - `test` gets a fresh random ID per invocation. The scenario's own destroy
#   step removes its containers; if the run fails or is interrupted, the
#   wrapper runs `molecule destroy` for the same ID, which only removes the
#   containers named with that ID. The ephemeral directory is removed after.
# - Other commands (converge, verify, login, destroy, ...) get an ID that is
#   stable for this checkout, role and scenario, so a debugging sequence of
#   separate invocations addresses the same containers while other roles and
#   scenarios keep their own. `destroy` removes that ephemeral directory.
#
# An exported MOLECULE_RUN_ID overrides both defaults. Give each scenario that
# runs at the same time its own ID: scenarios share platform base names.
set -euo pipefail

if [[ $# -lt 3 ]]; then
    echo "usage: $0 <role> <scenario> <molecule-command> [args...]" >&2
    exit 2
fi

role=$1
scenario=$2
command=$3
shift 3

repo_root=$(cd -- "$(dirname "$0")/.." && pwd -P)
role_dir="$repo_root/roles/$role"
if [[ ! -f "$role_dir/molecule/$scenario/molecule.yml" ]]; then
    echo "error: no Molecule scenario at roles/$role/molecule/$scenario" >&2
    exit 2
fi

random_hex() {
    od -An -N5 -tx1 /dev/urandom | tr -d ' \n'
}

checkout_id() {
    local digest identity
    identity="$repo_root"$'\n'"$role"$'\n'"$scenario"
    if command -v shasum >/dev/null 2>&1; then
        digest=$(printf '%s' "$identity" | shasum -a 256)
    else
        digest=$(printf '%s' "$identity" | sha256sum)
    fi
    printf 'wt%s' "${digest:0:10}"
}

if [[ -z "${MOLECULE_RUN_ID:-}" ]]; then
    if [[ "$command" == "test" ]]; then
        MOLECULE_RUN_ID="t$(random_hex)"
    else
        MOLECULE_RUN_ID=$(checkout_id)
    fi
fi
# The ID becomes part of Docker container names and container host names.
if [[ ! "$MOLECULE_RUN_ID" =~ ^[a-z0-9][a-z0-9-]{0,23}$ ]]; then
    echo "error: MOLECULE_RUN_ID must match ^[a-z0-9][a-z0-9-]{0,23}\$ (got '$MOLECULE_RUN_ID')" >&2
    exit 2
fi
export MOLECULE_RUN_ID

state_root="${OPS_LIBRARY_MOLECULE_STATE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/ops-library-molecule}"
run_dir="$state_root/$MOLECULE_RUN_ID/$role/$scenario"
export MOLECULE_EPHEMERAL_DIRECTORY="$run_dir/molecule"
# Molecule's prerun installs this checkout as the local.ops_library collection
# into $ANSIBLE_HOME/collections with --force. With the shared ~/.ansible,
# parallel checkouts race on that directory and use each other's role code.
# Give the run its own ANSIBLE_HOME and put the shared collections (for
# community.docker and friends) after it on the collection path.
shared_collections="${ANSIBLE_HOME:-$HOME/.ansible}/collections:/usr/share/ansible/collections"
export ANSIBLE_HOME="$run_dir/ansible"
export ANSIBLE_COLLECTIONS_PATH="$ANSIBLE_HOME/collections:${ANSIBLE_COLLECTIONS_PATH:-$shared_collections}"
mkdir -p "$MOLECULE_EPHEMERAL_DIRECTORY" "$ANSIBLE_HOME/collections"

echo "Molecule run id: $MOLECULE_RUN_ID (roles/$role/molecule/$scenario)"

cd "$role_dir"

remove_state() {
    rm -rf -- "$run_dir"
    rmdir -- "$state_root/$MOLECULE_RUN_ID/$role" "$state_root/$MOLECULE_RUN_ID" 2>/dev/null || true
}

if [[ "$command" == "test" ]]; then
    # Seconds since the epoch, so Ansible temp dirs created by this run
    # (ansible-tmp-<epoch>.<frac>-<pid>-<rand>) can be told from older ones.
    run_started=$(date +%s)
    # Molecule's docker driver creates containers with `async: ..., poll: 0`.
    # Ansible's async_wrapper calls setsid(), so those workers leave our
    # process group and survive stop_child. Wait for every async worker that
    # started during this run (its argv names an ansible-tmp-<epoch> dir no
    # older than the run) before destroying, or a late worker could create a
    # container after destroy. This only waits; it never signals processes,
    # so other runs' jobs (which may match too) are left alone.
    settle_async_jobs() {
        local limit=${OPS_LIBRARY_MOLECULE_ASYNC_SETTLE_TIMEOUT:-120}
        local deadline=$((SECONDS + limit))
        while ps axww -o command= 2>/dev/null | awk -v start="$run_started" '
            match($0, /ansible-tmp-[0-9]+/) {
                if (substr($0, RSTART + 12, RLENGTH - 12) + 0 >= start) found = 1
            }
            END { exit !found }'; do
            if (( SECONDS >= deadline )); then
                echo "Ansible async workers still running after ${limit}s; destroying anyway." >&2
                return 0
            fi
            sleep 1
        done
    }
    finish() {
        local status=$?
        trap - EXIT INT TERM
        if [[ $status -ne 0 ]]; then
            echo "Molecule test failed or was interrupted; destroying run $MOLECULE_RUN_ID containers..." >&2
            settle_async_jobs
            uv run molecule destroy -s "$scenario" || true
        fi
        remove_state
        exit "$status"
    }
    # Run the test as a background job in its own process group (set -m), so
    # INT/TERM reach this shell at once (bash defers traps while a foreground
    # child runs) and the whole Molecule tree (uv, molecule, ansible-playbook)
    # can be stopped before the EXIT trap destroys this run's containers.
    child=
    stop_child() {
        local code=$1 waited=0
        local limit=$(( ${OPS_LIBRARY_MOLECULE_STOP_TIMEOUT:-30} * 10 ))
        trap - INT TERM
        if [[ -n "$child" ]]; then
            kill -TERM -- "-$child" 2>/dev/null || true
            # Poll rather than wait: a child that ignores TERM must not block
            # escalation to KILL and the cleanup below.
            while kill -0 -- "-$child" 2>/dev/null; do
                if (( waited >= limit )); then
                    echo "Molecule test did not stop after TERM; sending KILL..." >&2
                    kill -KILL -- "-$child" 2>/dev/null || true
                    break
                fi
                sleep 0.1
                waited=$((waited + 1))
            done
            wait "$child" 2>/dev/null || true
        fi
        exit "$code"
    }
    trap finish EXIT
    trap 'stop_child 130' INT
    trap 'stop_child 143' TERM
    set -m
    uv run molecule test -s "$scenario" "$@" &
    child=$!
    set +m
    status=0
    wait "$child" || status=$?
    child=
    exit "$status"
else
    uv run molecule "$command" -s "$scenario" "$@"
    if [[ "$command" == "destroy" ]]; then
        remove_state
    fi
fi
