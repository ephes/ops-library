# software_live_remove

Stop and remove the `software_live` collector, timer and authenticated endpoint.
Traefik, OS maintenance, shared metrics accounts and package dependencies are not
changed. Existing JSON state is preserved unless `software_live_remove_data=true`.

```yaml
- role: local.ops_library.software_live_remove
  software_live_remove_data: false
```

Defaults expose the original config, state and installation directory paths.
Use the same paths as deployment. Removal requires dedicated directory names
containing `software-live` directly under `/etc`, `/var/lib` or `/usr/local/lib`;
broad parent paths and traversal are rejected. Disable the corresponding Nyxmon checks before
removal so intentionally retired endpoints are not treated as unexplained outages.
The deploy role's `nyxmon_disable` task entry disables explicit names while
preserving check history and unrelated checks. Removal is an operator action;
never invoke it as a response to an unhealthy software version.
