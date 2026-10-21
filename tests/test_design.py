"""Tests de persistance du design et de l'injection serveur (stdlib uniquement).

Lance Tars.py dans un sous-processus avec un port aléatoire et TARS_DATA
temporaire, puis vérifie /state, /design et l'injection dans index.html.

Exécution :
    python -m unittest tests.test_design -v
    python tests/test_design.py
"""

import http.client
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Tars.py"
TOKEN = "design-token"
NONCE = "design-nonce"


class DesignTest(unittest.TestCase):
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

    def _request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest(method, path)
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            data = body
            if data is not None and not isinstance(data, bytes):
                data = json.dumps(data).encode("utf-8")
            if data is not None:
                conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def _auth_headers(self, origin=None):
        headers = {"X-Tars-Token": TOKEN}
        if origin is not None:
            headers["Origin"] = origin
        return headers

    def _post_design(self, design, origin=None, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers.update(self._auth_headers(origin))
        elif origin is not None:
            headers["Origin"] = origin
        return self._request("POST", "/design", headers=headers, body={"design": design})

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def test_state_has_default_design(self):
        status, body = self._request("GET", "/state", headers=self._auth_headers())
        self.assertEqual(status, 200)
        state = json.loads(body.decode("utf-8"))
        self.assertEqual(state["design"], "monolithe")
        self.assertEqual(state["humour"], 60)
        self.assertEqual(state["honnetete"], 90)

    def test_post_design_valid_persists(self):
        status, body = self._post_design("editorial", origin=self.origin)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"design": "editorial"})

        status, body = self._request("GET", "/state", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8"))["design"], "editorial")

        saved = json.loads((Path(self.tmp.name) / "settings.json").read_text("utf-8"))
        self.assertEqual(saved["design"], "editorial")
        self.assertEqual(saved["humour"], 60)
        self.assertEqual(saved["honnetete"], 90)

    def test_post_design_unknown_is_400(self):
        status, body = self._post_design("neon", origin=self.origin)
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body.decode("utf-8")))

    def test_post_design_without_auth_is_401(self):
        status, _ = self._post_design("cyanotype", origin=self.origin, auth=False)
        self.assertEqual(status, 401)

    def test_post_design_bad_origin_is_403(self):
        status, _ = self._post_design("cyanotype", origin="https://evil.example")
        self.assertEqual(status, 403)

    def test_index_injects_data_design(self):
        status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertRegex(text, r'<html\b[^>]*\blang="fr"[^>]*\bdata-design="monolithe"[^>]*>')

        status, _ = self._post_design("cyanotype", origin=self.origin)
        self.assertEqual(status, 200)
        status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertRegex(text, r'<html\b[^>]*\blang="fr"[^>]*\bdata-design="cyanotype"[^>]*>')
        # Un seul attribut dans la balise <html> (les sélecteurs CSS html[data-design=...] ne comptent pas).
        html_tag = re.search(r"<html\b[^>]*>", text, re.I).group(0)
        self.assertEqual(html_tag.count("data-design="), 1)

    def test_invalid_persisted_design_falls_back(self):
        settings = Path(self.tmp.name) / "settings.json"
        settings.write_text(
            json.dumps({"humour": 30, "honnetete": 40, "design": '"><script>alert(1)</script>'}),
            "utf-8",
        )
        status, body = self._request("GET", "/state", headers=self._auth_headers())
        self.assertEqual(status, 200)
        state = json.loads(body.decode("utf-8"))
        self.assertEqual(state["design"], "monolithe")
        self.assertEqual(state["humour"], 30)
        self.assertEqual(state["honnetete"], 40)

        status, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertRegex(text, r'<html\b[^>]*\blang="fr"[^>]*\bdata-design="monolithe"[^>]*>')
        self.assertNotIn("<script>alert(1)</script>", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
