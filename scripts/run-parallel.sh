#!/usr/bin/env bash
# Run a list of jobs with a bounded number in parallel, one log file per job.
#
# Usage: scripts/run-parallel.sh [--jobs N|auto:N] [--log-dir DIR] [--label NAME]
#                                [--tail LINES] -- COMMAND < job-list
#
# Reads one job name per line from stdin and runs COMMAND (a bash snippet) for
# each with the job name in "$JOB", at most N at a time, in list order
# (auto:N: at most N and at most half the host's CPU count). Every
# job writes its output to <log-dir>/<job>.log and a line
# "<job> TAB <exit status> TAB <seconds>" to <log-dir>/results.tsv. When all
# jobs are done the script prints the jobs by duration, the tail of every
# failing job's log, and exits 1 if any job failed or did not finish (0 else).
# Unlike a chain of `just` dependencies, a failing job does not stop the jobs
# after it.
#
# --jobs 1 runs the list one after another and also streams each job's output
# to the terminal. The default log directory is
# ${XDG_CACHE_HOME:-~/.cache}/ops-library-runs/<label>-<time>-<pid>; it is kept
# after the run. Ctrl-C reaches every running job through the process group,
# so wrappers such as scripts/molecule-run.sh still clean up after themselves.
set -euo pipefail

if [[ "${1:-}" == "--run-one" ]]; then
    # Internal: run one job (called through xargs).
    export JOB=$2
    log="$RUN_PARALLEL_LOG_DIR/${JOB//\//__}.log"
    start=$(date +%s)
    if [[ "$RUN_PARALLEL_STREAM" == 1 ]]; then
        echo "==> $JOB"
        status=0
        bash -c "$RUN_PARALLEL_COMMAND" 2>&1 | tee "$log" || status=${PIPESTATUS[0]}
    else
        echo "[start] $JOB"
        status=0
        bash -c "$RUN_PARALLEL_COMMAND" >"$log" 2>&1 </dev/null || status=$?
    fi
    seconds=$(( $(date +%s) - start ))
    printf '%s\t%s\t%s\n' "$JOB" "$status" "$seconds" >>"$RUN_PARALLEL_LOG_DIR/results.tsv"
    if [[ $status -eq 0 ]]; then
        echo "[ok   ${seconds}s] $JOB"
    else
        echo "[FAIL ${seconds}s, exit $status] $JOB (log: $log)"
    fi
    # Always succeed, so xargs keeps starting the remaining jobs.
    exit 0
fi

jobs=4
log_dir=
label=run
tail_lines=40
while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs) jobs=$2; shift 2 ;;
        --log-dir) log_dir=$2; shift 2 ;;
        --label) label=$2; shift 2 ;;
        --tail) tail_lines=$2; shift 2 ;;
        --) shift; break ;;
        *) echo "usage: $0 [--jobs N] [--log-dir DIR] [--label NAME] [--tail LINES] -- COMMAND < job-list" >&2; exit 2 ;;
    esac
done
if [[ $# -ne 1 ]]; then
    echo "error: give exactly one COMMAND after --" >&2
    exit 2
fi
# auto:N = at most N and at most half the host's CPUs (at least 1), so several
# test runs on the same machine leave room for each other.
if [[ "$jobs" =~ ^auto:([1-9][0-9]*)$ ]]; then
    cap=${BASH_REMATCH[1]}
    cpus=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)
    jobs=$(( cpus / 2 ))
    (( jobs > cap )) && jobs=$cap
    (( jobs < 1 )) && jobs=1
fi
if [[ ! "$jobs" =~ ^[1-9][0-9]*$ ]]; then
    echo "error: --jobs must be a positive integer or auto:N (got '$jobs')" >&2
    exit 2
fi

job_list=()
while IFS= read -r line; do
    [[ -n "$line" ]] && job_list+=("$line")
done
if [[ ${#job_list[@]} -eq 0 ]]; then
    echo "No jobs given"
    exit 0
fi

if [[ -z "$log_dir" ]]; then
    log_dir="${XDG_CACHE_HOME:-$HOME/.cache}/ops-library-runs/$label-$(date +%Y%m%d-%H%M%S)-$$"
fi
mkdir -p "$log_dir"
: >"$log_dir/results.tsv"

export RUN_PARALLEL_LOG_DIR="$log_dir"
export RUN_PARALLEL_COMMAND=$1
export RUN_PARALLEL_STREAM=0
[[ "$jobs" == 1 ]] && RUN_PARALLEL_STREAM=1

echo "Running ${#job_list[@]} $label jobs, $jobs at a time; logs in $log_dir"
started=$(date +%s)
printf '%s\0' "${job_list[@]}" | xargs -0 -n 1 -P "$jobs" bash "$0" --run-one
elapsed=$(( $(date +%s) - started ))

failed=()
for job in "${job_list[@]}"; do
    status=$(awk -F'\t' -v j="$job" '$1 == j { s = $2 } END { print s }' "$log_dir/results.tsv")
    if [[ -z "$status" ]]; then
        failed+=("$job (did not finish)")
    elif [[ "$status" != 0 ]]; then
        failed+=("$job")
    fi
done

echo "========================================"
echo "$label: ${#job_list[@]} jobs in ${elapsed}s with --jobs $jobs (slowest first):"
sort -t$'\t' -k3,3nr "$log_dir/results.tsv" | awk -F'\t' '{ printf "  %5ss  %s  %s\n", $3, ($2 == 0 ? "ok  " : "FAIL"), $1 }'
if [[ ${#failed[@]} -gt 0 ]]; then
    if [[ "$jobs" != 1 ]]; then
        for job in "${failed[@]}"; do
            log="$log_dir/${job//\//__}.log"
            [[ -f "$log" ]] || continue
            echo "---------------------------------------- $job (last $tail_lines lines)"
            tail -n "$tail_lines" "$log"
        done
    fi
    echo "========================================"
    echo "FAILED ($label): ${failed[*]}"
    echo "Logs: $log_dir"
    echo "========================================"
    exit 1
fi
echo "All $label jobs passed. Logs: $log_dir"
