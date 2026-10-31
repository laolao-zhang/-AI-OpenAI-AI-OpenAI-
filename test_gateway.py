import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

import gateway
from mock_upstream import Mock


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mock = ThreadingHTTPServer(('127.0.0.1', 0), Mock)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.Handler)
        for server in (self.mock, self.server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        gateway.TOKEN = 'test-token'
        gateway.UPSTREAM = f'http://127.0.0.1:{self.mock.server_port}/v1/chat/completions'
        gateway.ACCOUNTS = [{'name': 'one', 'key': 'fake-key'}, {'name': 'two', 'key': 'fake-key'}]
        gateway.DAILY_LIMIT = 0
        gateway.NEXT = 0
        gateway.STATE = Path(self.tmp.name) / 'usage.json'

    def tearDown(self):
        for server in (self.server, self.mock):
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers = {'Authorization': 'Bearer test-token'} if auth else {}
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        res = conn.getresponse()
        content = res.read()
        code = res.status
        conn.close()
        return code, content

    def test_auth(self):
        self.assertEqual(self.call('GET', '/v1/models', auth=False)[0], 401)
        self.assertEqual(self.call('POST', '/v1/chat/completions', {'messages': []}, False)[0], 401)
        self.assertEqual(self.call('GET', '/admin/stats', auth=False)[0], 401)

    def test_rotation_and_quota(self):
        gateway.DAILY_LIMIT = 3
        self.assertEqual(self.call('POST', '/v1/chat/completions', {'messages': []})[0], 200)
        self.assertEqual(self.call('POST', '/v1/chat/completions', {'messages': []})[0], 200)
        self.assertEqual(self.call('POST', '/v1/chat/completions', {'messages': []})[0], 503)
        usage = json.loads(self.call('GET', '/admin/stats')[1])['usage']['accounts']
        self.assertEqual(usage['one']['tokens'], 3)
        self.assertEqual(usage['two']['tokens'], 3)

    def test_stream(self):
        code, result = self.call('POST', '/v1/chat/completions', {'messages': [], 'stream': True})
        self.assertEqual(code, 200)
        self.assertIn(b'data: [DONE]', result)
        self.assertEqual(json.loads(self.call('GET', '/admin/stats')[1])['usage']['accounts']['one']['tokens'], 3)


if __name__ == '__main__':
    unittest.main()

