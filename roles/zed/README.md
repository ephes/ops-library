# zed

Configures ZFS Event Daemon (ZED) email notifications and optional scrub timers.

## Variables

### Required

- `zed_email_to`

### Scrub timers

- `zed_manage_scrub_timer` (default: `true`)
- `zed_scrub_pools` (list of pool names)
