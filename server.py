#!/usr/bin/env python3
"""
Local development server for the Watchlist Dashboard.

Usage:
  python3 server.py

  GET  /              → serve dashboard.html
  GET  /update        → run generate.py, then git add/commit/push
"""

import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

PORT = 8000
BASE_DIR = Path(__file__).parent


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(fmt % args)

    def do_GET(self):
        if self.path in ('/', '/index.html', '/dashboard.html'):
            self._serve_file('dashboard.html', 'text/html; charset=utf-8')
        elif self.path == '/update':
            self._run_update()
        else:
            self.send_error(404)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _serve_file(self, name, mime):
        path = BASE_DIR / name
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _run_update(self):
        """Execute generate.py then git add/commit/push."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()

        log = []

        def run(cmd, **kw):
            r = subprocess.run(
                cmd, capture_output=True, text=True, cwd=BASE_DIR, **kw
            )
            out = (r.stdout + r.stderr).strip()
            if out:
                log.append(out)
            return r.returncode == 0

        ok = run(['python3', 'generate.py'])
        if not ok:
            self._write_json({'ok': False, 'log': log})
            return

        run(['git', 'add', 'dashboard.html'])

        # commit only if there are staged changes
        diff = subprocess.run(
            ['git', 'diff', '--cached', '--quiet'],
            cwd=BASE_DIR
        )
        if diff.returncode != 0:
            run(['git', 'commit', '-m', 'manual update'])
            run(['git', 'push'])
            log.append('✅ Pushed to GitHub.')
        else:
            log.append('ℹ️  No changes — skipped commit.')

        self._write_json({'ok': True, 'log': log})

    def _write_json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.wfile.write(data)


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    server = http.server.ThreadingHTTPServer(('', PORT), Handler)
    print(f'🚀  http://localhost:{PORT}')
    print('    /update → regenerate + git push')
    print('    Ctrl-C to stop\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
