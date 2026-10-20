"""Tests de sécurité du serveur TARS (stdlib uniquement).

Lance Tars.py dans un sous-processus avec un port aléatoire et vérifie
l'authentification, le bootstrap one-time, le contrôle Host/Origin et
l'absence de CORS.

Exécution :
    python -m unittest tests.test_security -v
    python tests/test_security.py
"""

import http.client
import http.cookiejar
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Tars.py"
TOKEN = "test-token"
NONCE = "test-nonce"


def _header(headers, name):
    name = name.lower()
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proc = None
        self.port = None
        self.addCleanup(self._cleanup)
        self._start_server()

    def _cleanup(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.proc is not None and self.proc.stdout is not None:
            self.proc.stdout.close()
        if self.tmp is not None:
            self.tmp.cleanup()

    def _start_server(self):
        env = os.environ.copy()
        for key in ("TARS_TOKEN", "TARS_BOOT_NONCE", "TARS_HOST", "TARS_PORT", "TARS_DATA"):
            env.pop(key, None)
        env.update({
            "TARS_MOCK": "1",
            "TARS_TOKEN": TOKEN,
            "TARS_BOOT_NONCE": NONCE,
            "TARS_DATA": self.tmp.name,
            "TARS_PORT": "0",
            "TARS_HOST": "127.0.0.1",
            "PYTHONIOENCODING": "utf-8",
        })
        self.proc = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        lines = queue.Queue()

        def pump():
            try:
                for line in self.proc.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                line = lines.get(timeout=max(0.1, deadline - time.time()))
            except queue.Empty:
                break
            if line is None:
                break
            match = re.search(r"TARS_READY port=(\d+)", line)
            if match:
                self.port = int(match.group(1))
                self.assertGreater(self.port, 0)
                return
        self.fail(f"serveur non prêt (code de sortie={self.proc.poll()})")

    def _request(self, method, path, headers=None, body=None, skip_host=False, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=skip_host)
            if host is not None:
                conn.putheader("Host", host)
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            data = body
            if data is not None and not isinstance(data, bytes):
                data = json.dumps(data).encode("utf-8")
            if data is not None:
                conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            response = conn.getresponse()
            payload = response.read()
            return response.status, response.getheaders(), payload
        finally:
            conn.close()

    def _boot(self):
        status, headers, _ = self._request("GET", f"/?boot={NONCE}")
        self.assertEqual(status, 302)
        set_cookie = _header(headers, "Set-Cookie")
        self.assertIsNotNone(set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        return set_cookie.split(";", 1)[0]

    def test_health_public(self):
        status, _, body = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})
        self.assertGreater(self.port, 0)

    def test_index_without_token_or_cookie(self):
        status, headers, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIsNone(_header(headers, "Set-Cookie"))
        text = body.decode("utf-8", "replace")
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(NONCE, text)

    def test_bootstrap_sets_httponly_cookie(self):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar),
            _NoRedirect,
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            opener.open(f"http://127.0.0.1:{self.port}/?boot={NONCE}", timeout=5)
        self.assertEqual(ctx.exception.code, 302)
        set_cookie = ctx.exception.headers.get("Set-Cookie")
        self.assertIsNotNone(set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        with opener.open(f"http://127.0.0.1:{self.port}/state", timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_bootstrap_nonce_is_one_time(self):
        self._boot()
        status, _, _ = self._request("GET", f"/?boot={NONCE}")
        self.assertEqual(status, 403)

    def test_state_requires_auth(self):
        status, _, _ = self._request("GET", "/state")
        self.assertEqual(status, 401)
        status, _, _ = self._request("GET", "/state", headers={"X-Tars-Token": TOKEN})
        self.assertEqual(status, 200)

    def test_post_config_evil_origin_without_auth(self):
        status, _, _ = self._request(
            "POST", "/config",
            headers={"Origin": "https://evil.example", "Content-Type": "application/json"},
            body={},
        )
        self.assertIn(status, (401, 403))

    def test_post_config_evil_origin_with_token(self):
        status, _, _ = self._request(
            "POST", "/config",
            headers={
                "Origin": "https://evil.example",
                "X-Tars-Token": TOKEN,
                "Content-Type": "application/json",
            },
            body={},
        )
        self.assertEqual(status, 403)

    def test_post_config_valid_origin_with_token(self):
        status, _, body = self._request(
            "POST", "/config",
            headers={
                "Origin": f"http://127.0.0.1:{self.port}",
                "X-Tars-Token": TOKEN,
                "Content-Type": "application/json",
            },
            body={},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["status"], "ok")

    def test_health_rejects_foreign_host(self):
        status, _, _ = self._request("GET", "/health", skip_host=True, host="evil.example")
        self.assertEqual(status, 403)

    def test_no_cors_headers(self):
        for method, path, headers in (
            ("GET", "/health", None),
            ("GET", "/state", None),
        ):
            _, response_headers, _ = self._request(method, path, headers=headers)
            self.assertIsNone(_header(response_headers, "Access-Control-Allow-Origin"))
        status, response_headers, _ = self._request("OPTIONS", "/health")
        self.assertEqual(status, 204)
        self.assertIsNone(_header(response_headers, "Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
