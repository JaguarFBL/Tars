"""Tests des fonctionnalités diagnostic, mémoire, historique et TTS (stdlib uniquement).

Lance Tars.py dans un sous-processus avec un port aléatoire et TARS_DATA
temporaire, puis vérifie les nouveaux endpoints sans appel réseau réel.

Exécution :
    python -m unittest tests.test_features -v
    python tests/test_features.py
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
TOKEN = "features-token"
NONCE = "features-nonce"
FACT_ID_RE = re.compile(r"^f_[0-9a-f]{12}$")
SESSION_RE = re.compile(r"^[0-9a-f]{12}$")


def _header(headers, name):
    name = name.lower()
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


class FeaturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proc = None
        self.port = None
        self.addCleanup(self._cleanup)
        self._start_server()

    def _stop_server(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.proc is not None and self.proc.stdout is not None:
            self.proc.stdout.close()
        self.proc = None
        self.port = None

    def _cleanup(self):
        self._stop_server()
        if self.tmp is not None:
            self.tmp.cleanup()

    def _env(self):
        env = os.environ.copy()
        for key in (
            "TARS_TOKEN", "TARS_BOOT_NONCE", "TARS_HOST", "TARS_PORT", "TARS_DATA",
            "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "TARS_PROVIDERS",
            "TARS_MODEL", "MISTRAL_MODEL", "GROQ_MODEL", "TARS_PIPER_BIN", "TARS_PIPER_MODEL",
        ):
            env.pop(key, None)
        env.update({
            "TARS_MOCK": "1",
            "TARS_TOKEN": TOKEN,
            "TARS_BOOT_NONCE": NONCE,
            "TARS_DATA": self.tmp.name,
            "TARS_PORT": "0",
            "TARS_HOST": "127.0.0.1",
            "TARS_PIPER_MODEL": "",
            "TARS_PIPER_BIN": "tars-piper-absent",
            "PYTHONIOENCODING": "utf-8",
        })
        return env

    def _start_server(self):
        env = self._env()
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

    def _request(self, method, path, headers=None, body=None, timeout=10):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
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
            return response.status, response.getheaders(), response.read()
        finally:
            conn.close()

    def _auth_headers(self, origin=None):
        headers = {"X-Tars-Token": TOKEN}
        if origin is not None:
            headers["Origin"] = origin
        return headers

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    def _post(self, path, payload, auth=True, origin=None, send_origin=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers.update(self._auth_headers(origin if send_origin else None))
        elif send_origin:
            headers["Origin"] = origin if origin is not None else self.origin
        return self._request("POST", path, headers=headers, body=payload)

    def _get_json(self, path):
        status, _, body = self._request("GET", path, headers=self._auth_headers())
        return status, json.loads(body.decode("utf-8"))

    def _chat(self, payload):
        status, _, body = self._request(
            "POST", "/chat",
            headers={
                "Content-Type": "application/json",
                "Origin": self.origin,
                "X-Tars-Token": TOKEN,
            },
            body=payload,
        )
        events = []
        if body:
            for line in body.decode("utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        return status, events

    def _memory_facts(self):
        status, data = self._get_json("/memory")
        self.assertEqual(status, 200)
        return data["facts"]

    def _add_fact(self, text):
        status, _, body = self._post("/memory", {"action": "add", "text": text})
        self.assertEqual(status, 200)
        return json.loads(body.decode("utf-8"))["fact"]

    def _journal_fact(self, text, when=None):
        record = {"t": time.time() if when is None else when, "kind": "fact", "text": text}
        with (Path(self.tmp.name) / "journal.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _run_consolidate(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "consolidate"],
            cwd=str(ROOT),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _context_pack(self):
        code = (
            "import json, Tars\n"
            "Tars.load_fact_events()\n"
            "facts, fresh = Tars.context_pack()\n"
            "print(json.dumps({'facts': facts, 'fresh': fresh}, ensure_ascii=False))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def _run_tars(self, code):
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    # ---------- Diagnostic ----------

    def test_diagnostic_requires_auth(self):
        status, _, _ = self._request("GET", "/diagnostic")
        self.assertEqual(status, 401)
        status, _, _ = self._request(
            "GET", "/diagnostic",
            headers={"X-Tars-Token": TOKEN, "Origin": "https://evil.example"},
        )
        self.assertEqual(status, 403)
        status, _, _ = self._request(
            "GET", "/diagnostic",
            headers={"X-Tars-Token": TOKEN, "Origin": self.origin},
        )
        self.assertEqual(status, 200)

    def test_diagnostic_shape_and_no_secret_leak(self):
        status, _, body = self._request("GET", "/diagnostic", headers=self._auth_headers())
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["server"], {"ok": True})
        self.assertTrue(data["auth"]["ok"])
        self.assertTrue(data["llm"]["ok"])
        self.assertTrue(data["llm"]["mock"])
        self.assertEqual(data["llm"]["active"], "mock")
        self.assertEqual([p["name"] for p in data["llm"]["providers"]], ["groq", "mistral", "anthropic"])
        for provider in data["llm"]["providers"]:
            self.assertEqual(set(provider), {"name", "configured", "model"})
            self.assertFalse(provider["configured"])
        self.assertEqual(data["stt"]["model"], "whisper-large-v3-turbo")
        self.assertFalse(data["stt"]["ok"])
        self.assertFalse(data["tts"]["piper"]["available"])
        self.assertEqual(data["tts"]["fallbacks"], ["web", "android"])
        self.assertEqual(data["memory"]["count"], 0)
        self.assertRegex(data["history"]["current"], SESSION_RE)
        self.assertEqual(set(data["last_error"]), {"message", "at", "source"})
        text = body.decode("utf-8")
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("api_key", text.lower())
        self.assertNotIn("bearer", text.lower())

    def test_sensitive_gets_reject_foreign_origin(self):
        for path in ("/memory", "/memory/export", "/history", "/history/0123456789ab"):
            status, _, _ = self._request(
                "GET", path,
                headers={"X-Tars-Token": TOKEN, "Origin": "https://evil.example"},
            )
            self.assertEqual(status, 403, path)
        for path in ("/memory", "/memory/export", "/history"):
            status, _, _ = self._request("GET", path, headers=self._auth_headers())
            self.assertEqual(status, 200, path)

    # ---------- Mémoire ----------

    def test_memory_requires_auth(self):
        status, _, _ = self._request("GET", "/memory")
        self.assertEqual(status, 401)
        status, _, _ = self._request("GET", "/memory/export")
        self.assertEqual(status, 401)

    def test_memory_crud_dedupe_and_export(self):
        status, _, body = self._post("/memory", {"action": "add", "text": "Le commandant aime le café."})
        self.assertEqual(status, 200)
        first = json.loads(body.decode("utf-8"))["fact"]
        self.assertRegex(first["id"], FACT_ID_RE)
        self.assertEqual(first["source"], "manuel")
        self.assertEqual(first["text"], "Le commandant aime le café.")
        self.assertIsInstance(first["created"], (int, float))

        status, _, body = self._post(
            "/memory", {"action": "add", "text": "LE COMMANDANT AIME LE CAFÉ."})
        self.assertEqual(status, 200)
        duplicate = json.loads(body.decode("utf-8"))["fact"]
        self.assertEqual(duplicate["id"], first["id"])

        status, _, body = self._post(
            "/memory", {"action": "add", "text": "Le commandant pilote un vaisseau."})
        self.assertEqual(status, 200)
        second = json.loads(body.decode("utf-8"))["fact"]
        self.assertNotEqual(second["id"], first["id"])

        status, data = self._get_json("/memory")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["facts"]), 2)

        status, _, body = self._post(
            "/memory", {"action": "update", "id": first["id"], "text": "Le commandant aime le thé."})
        self.assertEqual(status, 200)
        updated = json.loads(body.decode("utf-8"))["fact"]
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["text"], "Le commandant aime le thé.")

        status, headers, body = self._request(
            "GET", "/memory/export", headers=self._auth_headers())
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", _header(headers, "Content-Type"))
        self.assertIn('filename="tars-memoire.md"', _header(headers, "Content-Disposition"))
        exported = body.decode("utf-8")
        self.assertTrue(exported.startswith("# Mémoire TARS"))
        self.assertIn("- Le commandant aime le thé. (manuel,", exported)
        self.assertIn("- Le commandant pilote un vaisseau. (manuel,", exported)

        status, _, body = self._post("/memory", {"action": "delete", "id": second["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"status": "ok"})
        status, data = self._get_json("/memory")
        self.assertEqual(data["count"], 1)

        facts_md = (Path(self.tmp.name) / "facts.md").read_text("utf-8")
        self.assertTrue(facts_md.startswith("# Faits sur le commandant"))
        self.assertIn("- Le commandant aime le thé.", facts_md)
        self.assertNotIn("vaisseau", facts_md)
        facts_json = json.loads((Path(self.tmp.name) / "facts.json").read_text("utf-8"))
        self.assertEqual(len(facts_json["items"]), 1)

    def test_memory_validation_and_security(self):
        status, _, _ = self._post(
            "/memory", {"action": "add", "text": "Test."}, auth=False)
        self.assertEqual(status, 401)
        status, _, _ = self._post(
            "/memory", {"action": "add", "text": "Test."}, origin="https://evil.example")
        self.assertEqual(status, 403)

        for payload in (
            {"action": "add", "text": ""},
            {"action": "add", "text": "   "},
            {"action": "add", "text": "x" * 501},
            {"action": "add"},
            {"action": "inconnue"},
        ):
            status, _, _ = self._post("/memory", payload)
            self.assertEqual(status, 400, payload)

        status, _, _ = self._post(
            "/memory", {"action": "update", "id": "f_000000000000", "text": "Introuvable."})
        self.assertEqual(status, 404)
        status, _, _ = self._post(
            "/memory", {"action": "delete", "id": "f_000000000000"})
        self.assertEqual(status, 404)
        status, _, _ = self._post(
            "/memory", {"action": "update", "id": "pas-un-id", "text": "Test."})
        self.assertEqual(status, 400)
        status, _, _ = self._request(
            "POST", "/memory",
            headers={"Content-Type": "application/json", "X-Tars-Token": TOKEN, "Origin": self.origin},
            body=b"{",
        )
        self.assertEqual(status, 400)

    def test_memory_imports_existing_facts(self):
        (Path(self.tmp.name) / "facts.md").write_text(
            "# Faits sur le commandant\n\n- Premier fait\n- Deuxième fait\n", "utf-8")
        status, data = self._get_json("/memory")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 2)
        self.assertEqual([f["text"] for f in data["facts"]], ["Premier fait", "Deuxième fait"])
        self.assertEqual({f["source"] for f in data["facts"]}, {"import"})
        self.assertEqual(len({f["id"] for f in data["facts"]}), 2)
        self.assertTrue((Path(self.tmp.name) / "facts.json").is_file())

    def test_memory_delete_survives_consolidate_and_context_pack(self):
        text = "Le commandant aime le café."
        fact = self._add_fact(text)
        status, _, _ = self._post("/memory", {"action": "delete", "id": fact["id"]})
        self.assertEqual(status, 200)
        self._stop_server()
        self._journal_fact(text)

        pack = self._context_pack()
        self.assertNotIn(text, pack["facts"])
        self.assertNotIn(text, pack["fresh"])

        self._run_consolidate()
        data = json.loads((Path(self.tmp.name) / "facts.json").read_text("utf-8"))
        self.assertEqual(data["items"], [])

    def test_memory_clear_survives_consolidate_and_context_pack(self):
        text = "Le commandant aime le café."
        self._add_fact(text)
        self._journal_fact(text)
        status, _, _ = self._post("/memory", {"action": "clear"})
        self.assertEqual(status, 200)
        self._stop_server()

        pack = self._context_pack()
        self.assertNotIn(text, pack["facts"])
        self.assertNotIn(text, pack["fresh"])

        self._run_consolidate()
        data = json.loads((Path(self.tmp.name) / "facts.json").read_text("utf-8"))
        self.assertEqual(data["items"], [])

    def test_memory_clear_blocks_inflight_consolidation(self):
        text = "Le commandant aime le café."
        self._stop_server()
        code = (
            "import json, Tars\n"
            f"Tars.memory_add({text!r})\n"
            "epoch = Tars._load_facts_meta()['cleared_at']\n"
            "Tars.memory_clear()\n"
            f"result = Tars.sync_memory_from_lines(['- ' + {text!r}], expected_cleared_at=epoch)\n"
            "meta = Tars._load_facts_meta()\n"
            "print(json.dumps({'result': result, 'items': Tars.memory_items(), "
            "'tombstones': meta['tombstones'], 'cleared_at': meta['cleared_at']}, "
            "ensure_ascii=False))\n"
        )
        data = self._run_tars(code)
        self.assertIsNone(data["result"])
        self.assertEqual(data["items"], [])
        self.assertIn(text.lower(), data["tombstones"])
        self.assertGreater(data["cleared_at"], 0)

    def test_memory_update_does_not_restore_old_text(self):
        old = "Le commandant aime le café."
        new = "Le commandant aime le thé."
        fact = self._add_fact(old)
        status, _, body = self._post(
            "/memory", {"action": "update", "id": fact["id"], "text": new})
        self.assertEqual(status, 200)
        self._stop_server()
        self._journal_fact(old)

        pack = self._context_pack()
        self.assertNotIn(old, pack["fresh"])
        self.assertIn(new, pack["facts"])

        self._run_consolidate()
        data = json.loads((Path(self.tmp.name) / "facts.json").read_text("utf-8"))
        self.assertEqual([item["text"] for item in data["items"]], [new])

    # ---------- Historique ----------

    def test_history_requires_auth(self):
        status, _, _ = self._request("GET", "/history")
        self.assertEqual(status, 401)
        status, _, _ = self._request("GET", "/history/0123456789ab")
        self.assertEqual(status, 401)
        status, _, _ = self._request(
            "POST", "/history/open",
            headers={"Content-Type": "application/json", "Origin": self.origin},
            body={"id": "0123456789ab"},
        )
        self.assertEqual(status, 401)
        status, _, _ = self._request(
            "POST", "/history/new",
            headers={"Origin": self.origin},
        )
        self.assertEqual(status, 401)

    def test_history_after_chat_open_and_new(self):
        status, events = self._chat({"text": "Bonjour"})
        self.assertEqual(status, 200)
        self.assertTrue(any(event.get("done") for event in events))

        status, data = self._get_json("/history")
        self.assertEqual(status, 200)
        self.assertRegex(data["current"], SESSION_RE)
        self.assertEqual(len(data["sessions"]), 1)
        session = data["sessions"][0]
        self.assertEqual(session["id"], data["current"])
        self.assertEqual(session["turns"], 1)
        self.assertEqual(session["title"], "Bonjour")
        self.assertTrue(session["preview"])

        status, messages = self._get_json(f"/history/{session['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(messages["id"], session["id"])
        self.assertEqual([m["role"] for m in messages["messages"]], ["user", "assistant"])
        self.assertEqual(messages["messages"][0]["content"], "Bonjour")
        self.assertTrue(messages["messages"][1]["content"])

        status, _, body = self._post("/history/open", {"id": session["id"]})
        self.assertEqual(status, 200)
        opened = json.loads(body.decode("utf-8"))
        self.assertEqual(opened["id"], session["id"])
        self.assertEqual(len(opened["messages"]), 2)
        status, current = self._get_json("/history")
        self.assertEqual(current["current"], session["id"])

        status, _, body = self._post("/history/new", None)
        self.assertEqual(status, 200)
        new_id = json.loads(body.decode("utf-8"))["id"]
        self.assertRegex(new_id, SESSION_RE)
        self.assertNotEqual(new_id, session["id"])
        status, current = self._get_json("/history")
        self.assertEqual(current["current"], new_id)
        self.assertEqual(len(current["sessions"]), 1)

    def test_begin_turn_does_not_merge_duplicate_prompts(self):
        self._stop_server()
        code = (
            "import json, Tars\n"
            "Tars.history_new()\n"
            "g1, _, _ = Tars.begin_turn('Bonjour')\n"
            "g2, _, messages = Tars.begin_turn('Bonjour')\n"
            "late = Tars.finish_turn(g1, 'réponse tardive')\n"
            "with Tars.HIST_LOCK:\n"
            "    history = list(Tars.HISTORY)\n"
            "print(json.dumps({'messages': messages, 'late': late, 'history': history}, "
            "ensure_ascii=False))\n"
        )
        data = self._run_tars(code)
        self.assertEqual(data["messages"], [{"role": "user", "content": "Bonjour"}])
        self.assertNotIn("\n", data["messages"][0]["content"])
        self.assertFalse(data["late"])
        self.assertEqual(data["history"], [{"role": "user", "content": "Bonjour"}])

    def test_history_current_snapshot_before_persist(self):
        status, _, body = self._post("/history/new", None)
        self.assertEqual(status, 200)
        sid = json.loads(body.decode("utf-8"))["id"]
        self.assertFalse((Path(self.tmp.name) / "history.jsonl").exists())

        status, data = self._get_json(f"/history/{sid}")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"id": sid, "messages": []})
        status, _, body = self._post("/history/open", {"id": sid})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"id": sid, "messages": []})

        self._stop_server()
        code = (
            "import json, Tars\n"
            "sid = Tars.history_new()\n"
            "Tars.begin_turn('Bonjour')\n"
            "opened = Tars.history_open(sid)\n"
            "print(json.dumps({'opened': opened, 'persisted': Tars.HISTORY_FILE.exists()}, "
            "ensure_ascii=False))\n"
        )
        direct = self._run_tars(code)
        self.assertEqual(direct["opened"], [{"role": "user", "content": "Bonjour"}])
        self.assertFalse(direct["persisted"])

    def test_begin_regenerate_caps_context(self):
        self._stop_server()
        code = (
            "import json, Tars\n"
            "Tars.history_new()\n"
            "msgs = []\n"
            "for i in range(15):\n"
            "    msgs.append({'role': 'user', 'content': 'question %d' % i})\n"
            "    msgs.append({'role': 'assistant', 'content': 'réponse %d' % i})\n"
            "with Tars.HIST_LOCK:\n"
            "    Tars.HISTORY[:] = msgs\n"
            "gen, prev, out = Tars.begin_regenerate()\n"
            "with Tars.HIST_LOCK:\n"
            "    stored = len(Tars.HISTORY)\n"
            "print(json.dumps({'out': out, 'stored': stored}, ensure_ascii=False))\n"
        )
        data = self._run_tars(code)
        self.assertLessEqual(len(data["out"]), 20)
        self.assertEqual(data["out"][0]["role"], "user")
        self.assertEqual(data["out"][-1]["content"], "question 14")
        self.assertEqual(data["stored"], len(data["out"]))

    def test_history_persists_across_restart(self):
        status, _ = self._chat({"text": "Bonjour"})
        self.assertEqual(status, 200)
        status, data = self._get_json("/history")
        sid = data["current"]

        self._stop_server()
        self._start_server()

        status, data = self._get_json("/history")
        self.assertEqual(status, 200)
        self.assertEqual(data["current"], sid)
        self.assertEqual(len(data["sessions"]), 1)
        self.assertEqual(data["sessions"][0]["turns"], 1)
        status, messages = self._get_json(f"/history/{sid}")
        self.assertEqual(status, 200)
        self.assertEqual(len(messages["messages"]), 2)

    def test_regenerate_replaces_last_assistant(self):
        status, _ = self._chat({"text": "Bonjour"})
        self.assertEqual(status, 200)
        status, data = self._get_json("/history")
        sid = data["current"]
        status, before = self._get_json(f"/history/{sid}")
        user_count = sum(1 for m in before["messages"] if m["role"] == "user")
        assistant_count = sum(1 for m in before["messages"] if m["role"] == "assistant")

        status, events = self._chat({"regenerate": True, "text": "ignoré"})
        self.assertEqual(status, 200)
        self.assertTrue(any(event.get("done") for event in events))

        status, after = self._get_json(f"/history/{sid}")
        self.assertEqual(sum(1 for m in after["messages"] if m["role"] == "user"), user_count)
        self.assertEqual(sum(1 for m in after["messages"] if m["role"] == "assistant"), assistant_count)
        self.assertEqual(after["messages"][0]["content"], "Bonjour")
        self.assertTrue(after["messages"][-1]["content"])
        status, data = self._get_json("/history")
        self.assertEqual(data["sessions"][0]["turns"], 1)

        records = [
            json.loads(line)
            for line in (Path(self.tmp.name) / "history.jsonl").read_text("utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["user"], "Bonjour")

        status, _, _ = self._post("/history/new", None)
        self.assertEqual(status, 200)
        status, events = self._chat({"regenerate": True})
        self.assertEqual(status, 409)
        self.assertEqual(events, [{"error": "rien à régénérer"}])

    def test_regenerate_requires_matching_session_and_user(self):
        status, _ = self._chat({"text": "Bonjour"})
        self.assertEqual(status, 200)
        status, data = self._get_json("/history")
        self.assertEqual(status, 200)
        sid = data["current"]
        status, before = self._get_json(f"/history/{sid}")
        self.assertEqual(status, 200)

        status, events = self._chat(
            {"regenerate": True, "session": sid, "user": "Mauvais"})
        self.assertEqual(status, 409)
        self.assertEqual(events, [{"error": "rien à régénérer"}])
        status, unchanged = self._get_json(f"/history/{sid}")
        self.assertEqual(unchanged["messages"], before["messages"])

        status, events = self._chat(
            {"regenerate": True, "session": "000000000000", "user": "Bonjour"})
        self.assertEqual(status, 409)
        self.assertEqual(events, [{"error": "session obsolète"}])
        status, events = self._chat(
            {"regenerate": True, "session": "pas-un-id", "user": "Bonjour"})
        self.assertEqual(status, 409)
        self.assertEqual(events, [{"error": "session obsolète"}])
        status, unchanged = self._get_json(f"/history/{sid}")
        self.assertEqual(unchanged["messages"], before["messages"])

        status, events = self._chat(
            {"regenerate": True, "session": sid, "user": "  Bonjour  "})
        self.assertEqual(status, 200)
        self.assertTrue(any(event.get("done") for event in events))
        status, after = self._get_json(f"/history/{sid}")
        self.assertEqual(len(after["messages"]), len(before["messages"]))
        self.assertEqual(after["messages"][0]["content"], "Bonjour")
        records = [
            json.loads(line)
            for line in (Path(self.tmp.name) / "history.jsonl").read_text("utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["user"], "Bonjour")

    def test_history_handles_invalid_ids(self):
        status, _, _ = self._request(
            "GET", "/history/pas-un-id", headers=self._auth_headers())
        self.assertEqual(status, 404)
        status, _, _ = self._post("/history/open", {"id": "pas un id"})
        self.assertEqual(status, 400)
        status, _, _ = self._post("/history/open", {"id": "000000000000"})
        self.assertEqual(status, 404)

    # ---------- TTS ----------

    def test_tts_requires_auth(self):
        status, _, _ = self._request(
            "POST", "/tts",
            headers={"Content-Type": "application/json", "Origin": self.origin},
            body={"text": "Bonjour"},
        )
        self.assertEqual(status, 401)

    def test_tts_returns_503_without_piper(self):
        status, _, body = self._post("/tts", {"text": "Bonjour"})
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body.decode("utf-8")), {"error": "voix locale indisponible"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
