"""Local mock provider, for development only."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        self.send_response(200)
        if body.get('stream'):
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: {"choices":[],"usage":{"total_tokens":3}}\n\ndata: [DONE]\n\n')
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'choices': [{'message': {'role': 'assistant', 'content': 'mock reply'}}], 'usage': {'total_tokens': 3}}).encode())


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8900), Mock).serve_forever()

