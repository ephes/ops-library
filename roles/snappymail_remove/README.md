# SnappyMail Remove Role

Safely removes a SnappyMail deployment: nginx/Traefik config, PHP-FPM pool, application files, data directory, and service user.

## Safety

Set `snappymail_confirm_removal: true` to proceed. Otherwise the role fails immediately.

## What gets removed

- nginx site (`/etc/nginx/sites-available/snappymail` and enabled symlink)
- Traefik config (`/etc/traefik/dynamic/snappymail.yml`)
- PHP-FPM pool config(s) matching `/etc/php/*/fpm/pool.d/snappymail.conf`
- PHP-FPM sockets matching `/run/php/*snappymail*.sock`
- SnappyMail install dir (default `/opt/snappymail`)
- SnappyMail data dir (default `/mnt/cryptdata/snappymail`)
- SnappyMail system user/group
