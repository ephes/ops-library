# daybook_voice_memo_attention_notifier_remove

Revokes only the exact dedicated attention notifier SSH key and removes its
private configuration and standalone executable. Every other root authorization,
OpenClaw configuration, and Daybook tracking state remains untouched. Supplying a
key currently authorized differently, or leaving another notifier key present,
fails before removal. This also makes deploy/remove the explicit key rotation path.

Run as root/become on Linux. Defaults are in `defaults/main.yml`:

| Variable | Default / purpose |
| --- | --- |
| `daybook_voice_memo_attention_notifier_remove_confirm` | `false`; set `true` for removal |
| `daybook_voice_memo_attention_notifier_remove_public_key` | `CHANGEME`; the exact dedicated Ed25519 public key |

```yaml
- hosts: openclaw_host
  become: true
  roles:
    - role: local.ops_library.daybook_voice_memo_attention_notifier_remove
      vars:
        daybook_voice_memo_attention_notifier_remove_confirm: true
        daybook_voice_memo_attention_notifier_remove_public_key: "{{ private_attention_public_key }}"
```

The runner must be disabled before revocation. A send already in progress may
still finish; its persisted receipt/uncertain-delivery status requires normal
operator reconciliation. The role does not kill unrelated processes or turn
uncertain sends into safe retries.

The only removed files are `/etc/daybook-attention-notify.json` and
`/usr/local/libexec/daybook-attention-notify.py`. It never removes root's
`authorized_keys` file. Reinstall with `daybook_voice_memo_attention_notifier_deploy`
and configure the matching private key outside Git. No backup/restore role is
needed for these redeployable files; preserve runner tracking for recovery.

Run `just test-daybook-voice-memo-attention` for authorization preservation tests,
and the collection's `just test` and `just lint-strict` gates. Live transport
revocation must be recorded separately from these tests.

Authorization checks ignore commented-out lines, surrounding whitespace, and
trailing key comments. The actual forced-command options and key blob must still
match exactly; a differently authorized administration key is never adopted or
removed. A different live key bearing the exact notifier marker blocks rotation.
