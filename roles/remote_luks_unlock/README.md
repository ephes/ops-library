# Ansible Role: remote_luks_unlock

Enable remote unlocking of LUKS-encrypted root filesystems via SSH during early boot (initramfs) using Dropbear SSH server.

## Overview

This role enables headless servers with full disk encryption to be rebooted remotely without physical access. It installs and configures a minimal SSH server (Dropbear) in the initramfs environment that allows authorized users to remotely enter the LUKS passphrase during boot.

**Use case:** Servers with full disk encryption that need to reboot without physical presence (e.g., after power failures, kernel updates, or maintenance).

## Requirements

- **OS:** Ubuntu 20.04+ (or Debian-based systems with `dropbear-initramfs` package)
- **Encryption:** LUKS-encrypted root filesystem
- **Network:** Working network interface during boot
- **Dependencies:** The [`boot_visible_i915`](../boot_visible_i915/) role should be applied first for systems with Intel graphics (to ensure boot messages are visible)

## Role Variables

See [defaults/main.yml](defaults/main.yml) for all available variables. Key variables:

### Master Switch

```yaml
# Enable the remote unlock feature
remote_luks_unlock_enable: false

# Remove configuration when disabled (default: keep existing config)
remote_luks_unlock_cleanup_when_disabled: false
```

### Network Configuration

```yaml
# Network interface to use in initramfs
remote_luks_unlock_interface: "enp4s0"

# IP mode: "dhcp" or "static"
remote_luks_unlock_ip_mode: "dhcp"

# Static IP settings (required if ip_mode is "static")
remote_luks_unlock_static_ip: "192.168.1.100"
remote_luks_unlock_static_gateway: "192.168.1.1"
remote_luks_unlock_static_netmask: "255.255.255.0"
remote_luks_unlock_static_hostname: "{{ ansible_hostname }}"

# Network method: "grub_ip_param" (recommended) or "initramfs_conf"
remote_luks_unlock_network_method: "grub_ip_param"
```

### SSH Configuration

```yaml
# Dropbear SSH port (use non-standard port for security)
remote_luks_unlock_port: 2222

# SSH public keys authorized to unlock
remote_luks_unlock_authorized_keys:
  - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... user@host"
  - "ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB... admin@workstation"
```

### Advanced Options

```yaml
# Force removal of ALL network config (use with caution!)
remote_luks_unlock_force_remove_all_network_config: false

# Connection timeout in seconds
remote_luks_unlock_idle_timeout: 600

# Security hardening
remote_luks_unlock_no_password_auth: true
remote_luks_unlock_disable_forwarding: true
```

## Dependencies

None. This is a standalone role, but it's recommended to apply the [`boot_visible_i915`](../boot_visible_i915/) role first on systems with Intel graphics.

## Example Playbook

### Basic Usage with DHCP

```yaml
- hosts: servers
  become: yes
  roles:
    - role: local.ops_library.remote_luks_unlock
      vars:
        remote_luks_unlock_enable: true
        remote_luks_unlock_interface: "eth0"
        remote_luks_unlock_ip_mode: "dhcp"
        remote_luks_unlock_authorized_keys:
          - "{{ lookup('file', '~/.ssh/id_ed25519.pub') }}"
```

### Production Usage with Static IP

```yaml
- hosts: production_servers
  become: yes
  vars:
    sops_secrets: "{{ lookup('community.sops.sops', 'secrets/prod/bootstrap.yml') | from_yaml }}"

  roles:
    - role: local.ops_library.remote_luks_unlock
      vars:
        remote_luks_unlock_enable: true
        remote_luks_unlock_interface: "enp4s0"
        remote_luks_unlock_ip_mode: "static"
        remote_luks_unlock_static_ip: "192.168.178.94"
        remote_luks_unlock_static_gateway: "192.168.178.1"
        remote_luks_unlock_static_netmask: "255.255.255.0"
        remote_luks_unlock_port: 2222
        remote_luks_unlock_authorized_keys: "{{ sops_secrets.bootstrap_ssh_keys }}"
```

### Disabling and Cleaning Up

```yaml
- hosts: servers
  become: yes
  roles:
    - role: local.ops_library.remote_luks_unlock
      vars:
        remote_luks_unlock_enable: false
        remote_luks_unlock_cleanup_when_disabled: true
```

## Usage After Configuration

After the role has been applied and the system has been rebooted:

1. **System boots and waits at LUKS prompt** (in initramfs)

2. **Connect via SSH** from another machine:
   ```bash
   ssh -p 2222 -i ~/.ssh/unlock-macmini root@192.168.178.94
   ```

   Note: Use a dedicated SSH key for initramfs unlock (e.g., `~/.ssh/unlock-macmini`), separate from your regular system access keys.

   **Recommended:** Add an SSH config entry for convenience:
   ```
   Host macmini-unlock
       HostName 192.168.178.94
       User root
       Port 2222
       IdentityFile ~/.ssh/unlock-macmini
       StrictHostKeyChecking no
       UserKnownHostsFile /dev/null
   ```

   The `StrictHostKeyChecking` and `UserKnownHostsFile` options suppress host key warnings since Dropbear in initramfs uses different host keys than the booted system.

   Then simply: `ssh macmini-unlock`

3. **Unlock the encrypted disk** by running:
   ```bash
   cryptroot-unlock
   ```

   This command is available in the initramfs environment and will prompt for the LUKS passphrase.

4. **Enter the LUKS passphrase** when prompted

5. **System continues boot** and SSH connection drops as initramfs exits

6. **Normal SSH becomes available** on port 22 after boot completes

## Network Configuration Methods

This role supports two methods for configuring networking in initramfs:

### Method 1: GRUB ip= parameter (Recommended)

The `grub_ip_param` method adds networking configuration via kernel parameters in GRUB. This is more reliable and the recommended method.

**Example parameter:**
- DHCP: `ip=:::::enp4s0:dhcp`
- Static: `ip=192.168.178.94::192.168.178.1:255.255.255.0:macmini:enp4s0:none`

### Method 2: initramfs.conf

The `initramfs_conf` method configures networking via `/etc/initramfs-tools/initramfs.conf`. This is less common but may be needed in some scenarios.

**When switching methods:** The role automatically cleans up the configuration from the other method to prevent conflicts.

## Network Config Safety

By default, the role uses **scoped removal** when modifying network configuration:

- **Safe mode (default):** Only removes `ip=` parameters that reference your configured interface
- **Preserves:** NFS root, iSCSI, PXE, other interfaces

**Force mode:** Set `remote_luks_unlock_force_remove_all_network_config: true` to remove **all** network configuration. Only use if you're certain the system has no other network needs!

**Warning:** Many kernels only honor the **first** `ip=` parameter. If other `ip=` parameters exist, the role will warn you. Consider using force mode if networking doesn't work (but verify other parameters aren't needed first).

## Security Considerations

1. **SSH Keys:** Use dedicated SSH keys for initramfs unlock, separate from normal system access
2. **Network Exposure:** The Dropbear server is exposed before full system security is active
3. **Port:** Using a non-standard port (default: 2222) reduces exposure to automated attacks
4. **Authentication:** Only key-based authentication is enabled (no passwords)
5. **Forwarding:** Port forwarding is disabled by default
6. **Timeout:** Idle connections are automatically closed (default: 10 minutes)

## Verification

After applying the role, verify the configuration:

```bash
# Check package installation
dpkg -l | grep dropbear-initramfs

# Check authorized keys
cat /etc/dropbear/initramfs/authorized_keys

# Check Dropbear configuration
cat /etc/dropbear/initramfs/dropbear.conf

# Check GRUB configuration (if using grub_ip_param method)
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub

# Check initramfs configuration
grep -E '^(DROPBEAR|DEVICE|IP)=' /etc/initramfs-tools/initramfs.conf
```

After rebooting:

```bash
# From another machine, scan for the Dropbear port
nmap -p 2222 <server-ip>

# Test SSH connection
ssh -p 2222 root@<server-ip>
```

## Troubleshooting

### Dropbear not listening after reboot

**Possible causes:**
- Package not installed
- `DROPBEAR=y` not set in initramfs.conf
- Initramfs not rebuilt
- Network not configured

**Fix:** Re-run the role with verbose output:
```bash
ansible-playbook -vvv playbook.yml
```

### Can't connect - connection refused

**Possible causes:**
- Wrong IP address (DHCP assigned different IP)
- Network interface not available
- Firewall blocking port 2222

**Fix:**
- Use DHCP and scan the network for the IP
- Check router's DHCP leases
- Verify interface name is correct

### Authentication fails

**Possible causes:**
- Wrong SSH key
- Key not in authorized_keys
- Wrong permissions on authorized_keys

**Fix:**
- Verify key matches one in `remote_luks_unlock_authorized_keys`
- Check file permissions (should be 600)

### Network doesn't work in initramfs

**Possible causes:**
- Multiple `ip=` parameters (kernel only honors first one)
- Wrong interface name
- Missing network drivers/firmware

**Fix:**
- Check for warnings about multiple `ip=` parameters
- Consider setting `remote_luks_unlock_force_remove_all_network_config: true`
- Verify network interface name with `ip link show`

## Known Limitations

1. **Single interface:** Only one network interface can be configured
2. **IPv4 only:** IPv6 support not tested
3. **No VPN/VLAN:** Complex networking not supported in initramfs
4. **Interface names:** Must know the interface name (e.g., `enp4s0`)
5. **Kernel ip= precedence:** Multiple `ip=` parameters may cause conflicts

## References

- [Dropbear initramfs documentation](https://manpages.ubuntu.com/manpages/jammy/man8/dropbear.8.html)
- [Kernel ip= parameter format](https://www.kernel.org/doc/Documentation/filesystems/nfs/nfsroot.txt)
- [Remote LUKS unlock guide by Daniel Wayne Armstrong](https://www.dwarmstrong.org/remote-unlock-dropbear/)

## License

MIT

## Author Information

This role was created for the ops-library collection.
