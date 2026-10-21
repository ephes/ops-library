import base64
import hashlib
import hmac
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPT = Path(__file__).parents[1] / 'roles/container_ca_activate/files/livekit_idle.py'
spec = importlib.util.spec_from_file_location('idle', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestLivekitIdle(unittest.TestCase):
    def test_short_lived_token_and_aggregate_only_requests(self):
        calls = []
        def request(query, timeout):
            calls.append(query)
            self.assertEqual(timeout, 5)
            if query.full_url.endswith('/ListRooms'):
                return io.BytesIO(b'{"rooms":[]}')
            self.assertEqual(json.loads(query.data), {'active': True})
            return io.BytesIO(b'{"items":[]}')
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'server.yml'
            config.write_text(json.dumps({'keys': {'testkey': 'testsecret'}}))
            self.assertEqual(module.counts(config, request), {'active_rooms': 0, 'active_egress_jobs': 0})
        self.assertEqual(len(calls), 2)
        jwt = calls[0].headers['Authorization'].split()[1]
        header, claims, signature = jwt.split('.')
        payload = json.loads(base64.urlsafe_b64decode(claims + '=' * (-len(claims) % 4)))
        self.assertEqual(payload['video'], {'roomList': True, 'roomRecord': True})
        self.assertLessEqual(payload['exp'] - int(time.time()), 60)
        expected = base64.urlsafe_b64encode(hmac.new(b'testsecret', (header + '.' + claims).encode(), hashlib.sha256).digest()).decode().rstrip('=')
        self.assertEqual(signature, expected)

    def test_actual_cli_defers_active_room_without_emitting_metadata(self):
        paths = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                paths.append(self.path)
                body = b'{"rooms":[{"name":"private-room-name","metadata":"private-media"}]}' if self.path.endswith('/ListRooms') else b'{"items":[]}'
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / 'server.yml'
                config.write_text(json.dumps({'keys': {'testkey': 'testsecret'}, 'port': server.server_port}))
                result = subprocess.run([sys.executable, str(SCRIPT), str(config)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout), {'active_rooms': 1, 'active_egress_jobs': 0})
            for value in ('testsecret', 'private-room-name', 'private-media'):
                self.assertNotIn(value, result.stdout + result.stderr)
            self.assertEqual(paths, ['/twirp/livekit.RoomService/ListRooms', '/twirp/livekit.Egress/ListEgress'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
