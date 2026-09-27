# macos_smb_mount_keeper

Keeps SMB shares mounted at their exact `/Volumes/<share>` path in a macOS user's
session. A user LaunchAgent runs a small script at load and then every
`macos_smb_mount_keeper_interval_seconds`; for each configured share it:

- does nothing when the share is mounted from its server at exactly its mount
  point;
- only logs when the mount point is taken by anything else (a local volume whose
  name differs only in case sits on the same path, because `/Volumes` is
  case-insensitive) or the share is mounted at another point such as
  `/Volumes/<share>-1`;
- otherwise mounts it with Finder's `mount volume` through `osascript`, using the
  credential for that server and account in the user's login keychain, waits at
  most 90 seconds, and checks where it landed.

It never unmounts, ejects, renames or deletes anything. Whatever consumes the
share still verifies the mount's identity itself; the keeper only restores it
after sleep, a network change or a server restart. Only a change of a share's
outcome is logged, so a healthy mount writes nothing.

Store the credential once by mounting the share in Finder (⌘K) with "Remember
this password in my keychain". The first unattended mount may make macOS ask
whether the keychain item may be used; allow it once.

## Variables

| Variable | Default | Description |
|---|---|---|
| `macos_smb_mount_keeper_enabled` | `true` | Install and load the keeper; `false` unloads it and removes its plist, leaving mounts as they are |
| `macos_smb_mount_keeper_user` | `{{ ansible_user_id }}` | Logged-in macOS user whose session and keychain mount the shares |
| `macos_smb_mount_keeper_group` | `staff` | Group for installed files |
| `macos_smb_mount_keeper_home` | `{{ ansible_env.HOME }}` | That user's home |
| `macos_smb_mount_keeper_shares` | `[]` | Shares to keep: `server`, `share`, `account`, and `mount_point`, which must be `/Volumes/<share>` |
| `macos_smb_mount_keeper_interval_seconds` | `300` | How often the LaunchAgent runs (at least 60) |
| `macos_smb_mount_keeper_label` | `de.wersdoerfer.smb-mount-keeper` | LaunchAgent label |
| `macos_smb_mount_keeper_python` | `/usr/bin/python3` | Interpreter for the script |
| `macos_smb_mount_keeper_support_dir` | `<home>/Library/Application Support/SMB Mount Keeper` | Script, share list and last outcomes (mode 0700) |
| `macos_smb_mount_keeper_plist_path` | `<home>/Library/LaunchAgents/<label>.plist` | LaunchAgent property list |
| `macos_smb_mount_keeper_log_path` | `<home>/Library/Logs/smb-mount-keeper.log` | Outcome changes |

Run the role without `become`, as the configured user; it asserts that the
gathered user and home match. The LaunchAgent is limited to the Aqua session.

## Example

```yaml
- role: local.ops_library.macos_smb_mount_keeper
  macos_smb_mount_keeper_shares:
    - server: nas.example.org
      share: photos
      account: example
      mount_point: /Volumes/photos
```

Verify with:

```bash
launchctl print gui/$(id -u)/de.wersdoerfer.smb-mount-keeper
cat "$HOME/Library/Application Support/SMB Mount Keeper/state.json"
tail "$HOME/Library/Logs/smb-mount-keeper.log"
```

Outcomes: `mounted`, `remounted` (logged when it mounted the share), `occupied`,
`elsewhere`, `mount_failed`, `mount_timeout`, `mount_elsewhere`, `mount_occupied`.
