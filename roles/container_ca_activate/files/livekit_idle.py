#!/usr/bin/env python3
"""Read aggregate LiveKit room/job counts; never emit credentials or response contents."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import urllib.request


def token(key, secret):
    def encode(data):
        return base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).rstrip(b'=')
    now = int(time.time())
    message = encode({'alg': 'HS256', 'typ': 'JWT'}) + b'.' + encode({
        'iss': key, 'nbf': now - 5, 'exp': now + 60,
        'video': {'roomList': True, 'roomRecord': True}})
    return (message + b'.' + base64.urlsafe_b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).rstrip(b'=')).decode()


def counts(configuration, request=urllib.request.urlopen):
    import yaml
    config = yaml.safe_load(Path(configuration).read_text())
    keys = config['keys']
    key = next(iter(keys))
    bearer = token(key, keys[key])
    endpoint = 'http://127.0.0.1:' + str(int(config.get('port', 7880)))
    result = {}
    for service, method, body, field, output in (
        ('RoomService', 'ListRooms', {}, 'rooms', 'active_rooms'),
        ('Egress', 'ListEgress', {'active': True}, 'items', 'active_egress_jobs'),
    ):
        query = urllib.request.Request(endpoint + '/twirp/livekit.' + service + '/' + method,
                                       data=json.dumps(body).encode(),
                                       headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
        with request(query, timeout=5) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError('LiveKit aggregate response exceeds bounded size')
        payload = json.loads(data)
        values = payload.get(field, [])
        if not isinstance(values, list):
            raise ValueError('Unexpected LiveKit list response')
        result[output] = len(values)
    return result


if __name__ == '__main__':
    try:
        result = counts(sys.argv[1])
        print(json.dumps(result))
        if any(result.values()):
            raise ValueError('LiveKit is active; defer the restart window')
    except Exception as error:
        # No traceback/request/config contents: credentials and room metadata remain private.
        print('LiveKit idle preflight failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
