# daybook_voice_memo_attention_notifier_deploy

Installs the Daybook pilot's outbound-only Telegram notifier on the Linux
OpenClaw host. A newly generated dedicated SSH key can invoke only a fixed
Python program. It cannot request a shell, PTY, agent/X11/port forwarding, another
recipient, or a different command. Existing administration keys are preserved;
reusing a key with different existing authorization is rejected.

This role installs transport only. It never sends a message, reads OpenClaw
sessions, receives phone replies, or activates the attention pilot. The runner
owns notification intent, quota, and receipts; the working agent does not receive
this key. Native phone answering remains in the original provider conversation.

## Requirements

Linux root deployment, OpenSSH supporting the `restrict` authorized-key option,
`/usr/bin/python3` supporting Python 3.10 syntax, `/usr/bin/docker`, and the
existing `openclaw-gateway` container with its configured Telegram channel.
Supply the validated standalone `daybook/src/daybook/attention_notify.py` from
Daybook. Its request validation, neutral message generation, owner pinning,
`SSH_ORIGINAL_COMMAND` rejection, and bounded payload/transport behavior belong
to the application and must pass application tests before deployment.

## Variables

| Variable prefix `daybook_voice_memo_attention_notifier_` | Default / purpose |
| --- | --- |
| `script_src` | `CHANGEME`; absolute controller-local standalone `.py` source |
| `public_key` | `CHANGEME`; new dedicated Ed25519 public key, never an admin key |
| `native_host` | `CHANGEME`; neutral native host label verified by the runner |
| `recipient` | `CHANGEME`; verified owner Telegram recipient ID as a string |
| `container` | `openclaw-gateway`; fixed validated container |

Private host/recipient values and key authorization use `no_log: true`. The
configuration is root-owned 0600 at `/etc/daybook-attention-notify.json`; the
script is root-owned 0755 at `/usr/local/libexec/daybook-attention-notify.py`.
The fixed authorization is:

```text
restrict,command="/usr/bin/python3 -I /usr/local/libexec/daybook-attention-notify.py --config /etc/daybook-attention-notify.json"
```

`authorized_key` uses `exclusive: false` and manages only that dedicated key.
Do not replace the supplied public key with a general runner/owner login key.
Generate and protect its private half outside Git and the synced vault; configure
strict host-key checking in the private runner transport configuration.

## Example

```yaml
- hosts: openclaw_host
  become: true
  roles:
    - role: local.ops_library.daybook_voice_memo_attention_notifier_deploy
      vars:
        daybook_voice_memo_attention_notifier_script_src: /private/build/attention_notify.py
        daybook_voice_memo_attention_notifier_public_key: "{{ private_attention_public_key }}"
        daybook_voice_memo_attention_notifier_native_host: "{{ private_attention_host_label }}"
        daybook_voice_memo_attention_notifier_recipient: "{{ private_verified_owner_recipient }}"
```

## Validation and removal

Run `uv run python -m unittest tests.test_daybook_voice_memo_attention_notifier_deploy`
and the collection's `just test` and `just lint-strict`. Deployment alone does not
prove recipient delivery or a native phone round trip. Live synthetic sends must
use the owner-authorized profile and be recorded separately.

To revoke transport, use `daybook_voice_memo_attention_notifier_remove` with
explicit removal confirmation and the same dedicated public key. It preserves
all other root keys and runner tracking. Deployment rejects a different live key bearing the exact
`daybook-attention-notifier` marker: revoke it before installing a replacement.
An out-of-band key without that marker is outside this identity check; inspect
such authorizations explicitly during transport rotation. There is no
backup/restore role for redeployable script/configuration files. Preserve private
runner state and unrelated OpenClaw configuration during transport changes.

Authorization checks ignore commented-out lines, surrounding whitespace, and
trailing key comments. The actual forced-command options and key blob must still
match exactly; a differently authorized administration key is never adopted or
removed. A different live key bearing the exact notifier marker blocks rotation.
