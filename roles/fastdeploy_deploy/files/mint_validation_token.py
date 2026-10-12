"""Print a short-lived FastDeploy user access token for the rollout check.

Run with FastDeploy's own interpreter and the site directory as working
directory. FastDeploy's ``create_access_token`` signs the token with the
SECRET_KEY and algorithm of its own settings (the site's ``.env``), so this
needs no JWT library of its own and no secret on the command line.

stdin: a JSON object ``{"user": <name>, "ttl_seconds": <int>}``.
stdout: the token.
"""

import json
import sys
from datetime import timedelta

sys.path.insert(0, "src")

from deploy.auth import create_access_token  # noqa: E402

request = json.load(sys.stdin)
print(
    create_access_token(
        {"user": request["user"], "type": "user"},
        timedelta(seconds=int(request["ttl_seconds"])),
    )
)
