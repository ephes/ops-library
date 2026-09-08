# daybook_voice_memo_attention_remove

Disables and unloads only the Daybook voice-memo attention LaunchAgent, verifies
that it is unloaded, then removes its plist. It preserves the installed wheel,
virtual environment, private configuration, tracking state, logs, and activation
markers. It intentionally leaves the persistent per-user launchd disabled
override in place, even after removing the plist. A later approved activation
requires `launchctl enable gui/<uid>/<label>` followed by bootstrapping the
reinstalled plist; the explicit enable override takes precedence over the
plist's `Disabled: true`. Reinstalling or editing the plist alone does not clear
that override. It does not affect the voice-memo importer or other native sessions.

## Requirements and variables

Run with root/become privileges on macOS while the selected owner has an active
Aqua GUI domain. All variables are listed in `defaults/main.yml`.

| Variable | Default |
| --- | --- |
| `daybook_voice_memo_attention_remove_confirm` | `false`; must explicitly be `true` |
| `daybook_voice_memo_attention_remove_service_user` | `CHANGEME`; required non-root owner |
| `daybook_voice_memo_attention_remove_service_home` | `/Users/<service_user>` |
| `daybook_voice_memo_attention_remove_launchd_label` | `de.wersdoerfer.daybook.voice-memo-attention` |

Paths and label are fixed by validation to prevent removing unrelated services.
The confirmation is a deployment input, not permission to delete tracking data.

```yaml
- hosts: macos_owner_host
  become: true
  roles:
    - role: local.ops_library.daybook_voice_memo_attention_remove
      vars:
        daybook_voice_memo_attention_remove_confirm: true
        daybook_voice_memo_attention_remove_service_user: example
```

Reinstall with `daybook_voice_memo_attention_deploy`; it remains disabled and
preserves existing state. Never delete state to manufacture a fresh baseline.
This partial pilot provides no automatic backup, restore, or activation path.
