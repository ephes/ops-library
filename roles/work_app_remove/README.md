# Work App Remove Role

Removes the work app: stops and deletes the `work-app` systemd unit, deletes
the Traefik config and, by default, the SQLite database, the home directory
and the `work` user and group. Copy of `homelab_remove`.

`work_app_remove_confirm: true` is required. When the database would be
deleted, the role pauses unless `work_app_remove_auto_confirm: true`.
To keep the database, set `work_app_remove_database`, `work_app_remove_home`
and `work_app_remove_user` to `false` (the database lives in the home directory;
the role refuses the inconsistent combination). With
`work_app_remove_user: true` and `work_app_remove_home: false` the account is
deleted but the home directory stays. All flags are parsed with `| bool`, so
string values from `-e` (`"false"`) behave as expected.

## License

MIT
