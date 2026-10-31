"""Local-first OpenAI-style gateway. Credentials are supplied by the operator."""
import datetime
import hmac
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN = os.environ.get('GATEWAY_TOKEN', '')
UPSTREAM = os.environ.get('UPSTREAM_URL', '')
ACCOUNTS = json.loads(os.environ.get('UPSTREAM_ACCOUNTS', '[]'))
MODEL = os.environ.get('GATEWAY_MODEL', 'default')
DAILY_LIMIT = int(os.environ.get('DAILY_TOKEN_LIMIT', '0'))
STATE = Path(os.environ.get('STATE_FILE', 'data/usage.json'))
LOCK = threading.Lock()
NEXT = 0


def load_usage():
    try:
        data = json.loads(STATE.read_text(encoding='utf-8'))
        return data if data.get('date') == datetime.date.today().isoformat() else {}
    except FileNotFoundError:
        return {}


def choose_account():
    global NEXT
    with LOCK:
        usage = load_usage().get('accounts', {})
        for _ in ACCOUNTS:
            account = ACCOUNTS[NEXT % len(ACCOUNTS)]
            NEXT += 1
            if DAILY_LIMIT <= 0 or usage.get(account['name'], {}).get('tokens', 0) < DAILY_LIMIT:
                return account
        return None


def record_usage(name, tokens):
    with LOCK:
        data = load_usage()
        data['date'] = datetime.date.today().isoformat()
        entry = data.setdefault('accounts', {}).setdefault(name, {'calls': 0, 'tokens': 0})
        entry['calls'] += 1
        entry['tokens'] += max(0, int(tokens or 0))
        STATE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, STATE)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        return bool(TOKEN) and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN)

    def do_GET(self):
        if self.path == '/health':
            return self.send_json(200, {'ok': True})
        if self.path == '/admin':
            data = Path(__file__).with_name('admin.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if not self.authed():
            return self.send_json(401, {'error': {'message': 'unauthorized'}})
        if self.path == '/v1/models':
            return self.send_json(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model'}]})
        if self.path == '/admin/stats':
            with LOCK:
                data = load_usage()
            return self.send_json(200, {'usage': data, 'daily_token_limit': DAILY_LIMIT})
        self.send_json(404, {'error': {'message': 'not found'}})

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            self.close_connection = True
            return self.send_json(404, {'error': {'message': 'not found'}})
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.close_connection = True
            return self.send_json(400, {'error': {'message': 'invalid content length'}})
        if size < 0 or size > 1048576:
            self.close_connection = True
            return self.send_json(413, {'error': {'message': 'request too large'}})
        raw = self.rfile.read(size)
        if not self.authed():
            return self.send_json(401, {'error': {'message': 'unauthorized'}})
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or not isinstance(body.get('messages'), list):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {'error': {'message': 'invalid request'}})
        account = choose_account()
        if not UPSTREAM or account is None:
            return self.send_json(503, {'error': {'message': 'no available upstream account'}})
        req = urllib.request.Request(UPSTREAM, data=json.dumps(body).encode(), method='POST', headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + account['key']})
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                if body.get('stream'):
                    self.send_response(response.status)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    tokens = 0
                    for line in response:
                        self.wfile.write(line)
                        self.wfile.flush()
                        if line.startswith(b'data:'):
                            try:
                                tokens = json.loads(line[5:]).get('usage', {}).get('total_tokens', tokens)
                            except (ValueError, AttributeError):
                                pass
                    record_usage(account['name'], tokens)
                else:
                    data = response.read()
                    try:
                        tokens = json.loads(data).get('usage', {}).get('total_tokens', 0)
                    except (ValueError, AttributeError):
                        tokens = 0
                    record_usage(account['name'], tokens)
                    self.send_response(response.status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
        except urllib.error.HTTPError as exc:
            self.send_json(exc.code, {'error': {'message': 'upstream rejected request'}})
        except (urllib.error.URLError, TimeoutError):
            self.send_json(502, {'error': {'message': 'upstream unavailable'}})


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('GATEWAY_TOKEN is required')
    if any(not isinstance(a, dict) or not a.get('name') or not a.get('key') for a in ACCOUNTS):
        raise SystemExit('UPSTREAM_ACCOUNTS must contain name and key')
    ThreadingHTTPServer((os.environ.get('GATEWAY_HOST', '127.0.0.1'), int(os.environ.get('GATEWAY_PORT', '8899'))), Handler).serve_forever()

