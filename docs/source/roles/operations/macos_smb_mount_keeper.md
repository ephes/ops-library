# macOS SMB Mount Keeper

The `macos_smb_mount_keeper` role installs a user LaunchAgent that remounts SMB
shares at their exact `/Volumes/<share>` path after sleep, a network change or a
server restart, using the credential in the user's login keychain.

The role only ever mounts: it never unmounts, ejects or deletes, and it leaves a
mount point that anything else occupies alone. See the
[complete role reference](https://github.com/ephes/ops-library/blob/main/roles/macos_smb_mount_keeper/README.md)
for variables, examples, and verification commands.
