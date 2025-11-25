# boot_visible_i915

Ansible role to ensure visible boot output (GRUB menu, kernel messages, LUKS passphrase prompt) on Ubuntu systems with Intel i915 graphics and full disk encryption.

## Problem

After installing Ubuntu with full disk encryption on systems with Intel integrated graphics (especially T2 Mac Minis), the boot process shows a black screen until after the passphrase is entered "blindly". This happens because:

1. The `i915` kernel module is not loaded in the initramfs
2. Plymouth splash screen hides all boot output
3. GRUB may be misconfigured for graphics output

This makes initial setup difficult, troubleshooting impossible, and remote unlock setup challenging.

## Solution

This role:
- Loads the `i915` driver early in the boot process (initramfs)
- Removes any `i915` blacklist entries
- Configures GRUB for visible text output
- Removes Plymouth splash and quiet mode
- Shows the GRUB menu for a configurable timeout

## Requirements

- Ubuntu 22.04 LTS or 24.04 LTS
- Intel integrated graphics (i915 driver)
- System using GRUB bootloader
- Root/sudo access

## Role Variables

### i915 Configuration

```yaml
# Enable i915 in initramfs
boot_visible_enable_i915: true

# Remove i915 blacklist entries
boot_visible_remove_i915_blacklist: true
```

### GRUB Display Settings

```yaml
# Force text console (safe, conservative default)
boot_visible_grub_terminal: "console"

# Text mode handoff to kernel (safe default)
boot_visible_grub_gfxpayload: "text"
```

### GRUB Kernel Command Line

```yaml
# Whether to manage GRUB config
boot_visible_modify_grub_cmdline: true

# Base kernel command line (Ubuntu defaults)
# This is the starting point before applying removals and extras
boot_visible_grub_base_cmdline: "quiet splash"

# Remove splash screen
boot_visible_grub_remove_splash: true

# Remove quiet mode (show kernel messages)
boot_visible_grub_remove_quiet: true

# Remove nomodeset (allows i915 to load)
# NOTE: Only removes nomodeset if present in base_cmdline or extra_params
# Default base_cmdline doesn't include it, so this is defensive/no-op by default
boot_visible_grub_remove_nomodeset: true

# Additional kernel parameters
boot_visible_grub_extra_params: ""
```

**How removal flags work:**
- The role starts with `boot_visible_grub_base_cmdline` (default: `"quiet splash"`)
- Applies removal filters based on `boot_visible_grub_remove_*` flags
- Adds any `boot_visible_grub_extra_params`
- Example: With defaults, result is empty cmdline (quiet and splash removed)
- The `remove_nomodeset` flag is defensive - it removes `nomodeset` if you add it via `base_cmdline` or `extra_params`

### GRUB Menu

```yaml
# Show GRUB menu
boot_visible_show_grub_menu: true

# Menu timeout in seconds
boot_visible_grub_timeout: 5

# Backup /etc/default/grub before overwriting
boot_visible_grub_backup: true
```

## Example Playbooks

### Basic Usage (Bootstrap)

```yaml
---
- name: Bootstrap server with visible boot
  hosts: servers
  become: yes

  roles:
    - role: boot_visible_i915
```

### With Custom Parameters

```yaml
---
- name: Configure visible boot with network parameters
  hosts: servers
  become: yes

  roles:
    - role: boot_visible_i915
      vars:
        boot_visible_grub_timeout: 10
        boot_visible_grub_extra_params: "ip=dhcp"
```

### Minimal Visibility (Keep Some Quiet)

```yaml
---
- name: Visible LUKS prompt but quieter boot
  hosts: servers
  become: yes

  roles:
    - role: boot_visible_i915
      vars:
        boot_visible_grub_remove_quiet: false  # Keep quiet mode
        boot_visible_grub_remove_splash: true  # But remove splash
        boot_visible_show_grub_menu: false     # Hide GRUB menu
```

## Important Notes

### GRUB Configuration Management

This role **fully manages `/etc/default/grub`** via a template. This means:

- **Local edits to `/etc/default/grub` will be overwritten**
- A backup is created automatically (`.bak` file) if `boot_visible_grub_backup: true`
- To customize GRUB settings, use role variables instead of editing the file
- The role "owns" this configuration file

### After Running This Role

1. **Reboot required** - Changes take effect on next boot
2. **Expected behavior**:
   - GRUB menu appears for configured timeout (if enabled)
   - Kernel boot messages are visible
   - LUKS passphrase prompt is clearly visible
3. **Handlers**: The role triggers `update-initramfs` and `update-grub` automatically

### Idempotency

- Re-running the role is safe and idempotent
- Handlers only fire when changes are made
- No changes = no handler execution = no unnecessary initramfs/grub updates

## Testing

After applying the role:

1. **Verify configuration**:
   ```bash
   # Check i915 in initramfs
   grep i915 /etc/initramfs-tools/modules

   # Check GRUB config
   cat /etc/default/grub
   ```

2. **Reboot and observe**:
   ```bash
   sudo reboot
   ```

   Watch the screen for:
   - GRUB menu (if enabled)
   - Kernel boot messages
   - Visible LUKS passphrase prompt

3. **Post-reboot verification**:
   ```bash
   # Check i915 is loaded
   lsmod | grep i915

   # Check kernel command line
   cat /proc/cmdline
   ```

## Troubleshooting

### Still seeing black screen

**During GRUB**:
- Check that `boot_visible_grub_terminal: "console"` is set
- Try different `boot_visible_grub_gfxpayload` values: `"text"`, `"keep"`, or `"1024x768"`

**During kernel boot**:
- Verify `i915` is in `/etc/initramfs-tools/modules`
- Check no blacklist files exist: `grep -r "blacklist i915" /etc/modprobe.d/`
- Verify `quiet` and `splash` are removed from `/etc/default/grub`

**At LUKS prompt**:
- This is the most common issue - should be fixed by loading i915 early
- Verify `update-initramfs` ran successfully

### Need to revert changes

If you have issues and need to revert:

```bash
# Restore backup
sudo cp /etc/default/grub.bak /etc/default/grub
sudo update-grub

# Remove i915 from initramfs
sudo sed -i '/^i915$/d' /etc/initramfs-tools/modules
sudo update-initramfs -u -k all

# Reboot
sudo reboot
```

## Platform-Specific Notes

### T2 Mac Minis

This role was specifically designed for T2 Mac Minis running Ubuntu with LUKS encryption, but works on any Intel graphics system. The conservative defaults (text mode everywhere) ensure compatibility.

### Ubuntu Versions

- **22.04 LTS (Jammy)**: Fully supported
- **24.04 LTS (Noble)**: Fully supported
- Earlier versions: May work but untested

## License

MIT

## Author

Jochen Wersdörfer

## Contributing

Contributions welcome! This role is public and intended to help others with similar boot visibility issues.
