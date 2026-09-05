# macOS Time Machine Exclusions

The `macos_time_machine_exclusions` role installs a user LaunchAgent that
reapplies audited Time Machine exclusions once a day. It is intended for
reproducible build outputs that may be deleted and recreated with a new inode.

The role is deliberately non-destructive: it does not remove client data,
delete backup history, or compact sparsebundles. See the
[complete role reference](https://github.com/ephes/ops-library/blob/main/roles/macos_time_machine_exclusions/README.md)
for variables, examples, and verification commands.
