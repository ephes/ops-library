# macos_time_machine_exclusions

Idempotently applies user-scoped Time Machine exclusions on macOS during role
execution and installs a daily LaunchAgent that reapplies them when ignored
build directories are recreated.

The role deliberately does not delete local files, thin Time Machine history,
or compact sparsebundles. It calls `tmutil addexclusion` without `-p`, so it can
run as the logged-in user without administrator access. The exclusion follows
the current inode; the daily run restores it after a configured path is
recreated.

## Variables

| Variable | Default | Description |
|---|---|---|
| `macos_time_machine_exclusions_enabled` | `true` | Install and run exclusion enforcement |
| `macos_time_machine_exclusions_user` | `{{ ansible_user_id }}` | Logged-in macOS user that owns the LaunchAgent |
| `macos_time_machine_exclusions_group` | `staff` | Group for installed user files |
| `macos_time_machine_exclusions_home` | `{{ ansible_env.HOME }}` | User home containing LaunchAgents and support files |
| `macos_time_machine_exclusions_paths` | `[]` | Absolute, non-root paths to exclude when they exist |
| `macos_time_machine_exclusions_label` | `de.wersdoerfer.time-machine-exclusions` | LaunchAgent label |
| `macos_time_machine_exclusions_hour` | `3` | Daily LaunchAgent hour |
| `macos_time_machine_exclusions_minute` | `5` | Daily LaunchAgent minute |
| `macos_time_machine_exclusions_script_path` | `<home>/Library/Application Support/Time Machine Exclusions/apply-exclusions` | Managed enforcement script |
| `macos_time_machine_exclusions_plist_path` | `<home>/Library/LaunchAgents/<label>.plist` | Managed LaunchAgent property list |
| `macos_time_machine_exclusions_log_path` | `<home>/Library/Logs/time-machine-exclusions.log` | Combined LaunchAgent output log |

Only list reproducible or independently protected paths. Do not exclude a
project root merely because it is usually in Git: uncommitted and untracked
work still needs protection.

Run the role without `become`, as the same logged-in user named by
`macos_time_machine_exclusions_user`. The role validates that the gathered user
and home match the configured values so it cannot silently install an unusable
LaunchAgent under another account. A transient/nonzero `launchctl bootout` is
best effort because `bootstrap` is the authoritative convergence step; the
bootstrap operation is retried. A steady-state role run reports changed only
when the script actually adds a missing exclusion.

## Example

```yaml
- role: local.ops_library.macos_time_machine_exclusions
  macos_time_machine_exclusions_paths:
    - /Users/example/project/.venv
    - /Users/example/project/build
```

Verify with:

```bash
tmutil isexcluded /Users/example/project/build
launchctl print gui/$(id -u)/de.wersdoerfer.time-machine-exclusions
```

## Limitations

Paths protected by macOS privacy controls (TCC), such as `~/Library/Containers`
and `~/Library/Mail`, are not visible to the launchd-run agent. For those the
agent reports the path as included and `tmutil addexclusion` fails with
`Error (100001)` / `EINVAL`, and the nightly run exits non-zero. Do not list
such paths here. Apply a one-time sticky exclusion from an SSH or Terminal
session that has Full Disk Access instead, and confirm with `tmutil isexcluded`;
the exclusion follows the inode, so it persists until the bundle is recreated.
