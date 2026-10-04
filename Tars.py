#!/usr/bin/env python3
"""TARS pas tars : serveur vocal-texte, 100% local, zéro dépendance (stdlib uniquement).

Lancer :   python3 Tars.py
Ouvrir :   http://localhost:8000   (localhost = contexte sécurisé, le micro marche)
Nuit :     python3 Tars.py consolidate     (journal -> faits propres)
Test :     TARS_MOCK=1 python3 Tars.py     (faux LLM, aucune clé nécessaire)
"""
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("TARS_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
JOURNAL, FACTS, SETTINGS = DATA / "journal.jsonl", DATA / "facts.md", DATA / "settings.json"
MARK = DATA / "consolidated_until.txt"

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = os.environ.get("TARS_MODEL", "claude-haiku-4-5-20251001")  # rapide : la latence prime
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-tiny")
TOKEN = os.environ.get("TARS_TOKEN", "")  # optionnel, même en local pour la compatibilité
HOST = os.environ.get("TARS_HOST", "127.0.0.1")
PORT = int(os.environ.get("TARS_PORT", "8000"))
MOCK = os.environ.get("TARS_MOCK") == "1"

# État global pour le widget
CURRENT_STATE = {"status": "off", "last_activity": 0}
STATE_LOCK = threading.Lock()

LOCK = threading.Lock()
HISTORY = []  # messages de la session en cours (RAM)

# ---------- réglages persistants ----------

def load_settings():
    try:
        s = json.loads(SETTINGS.read_text("utf-8"))
    except (OSError, ValueError):
        s = {}
    return {"humour": int(s.get("humour", 60)), "honnetete": int(s.get("honnetete", 90))}


def save_settings(s):
    SETTINGS.write_text(json.dumps(s), "utf-8")


_SET_RE = re.compile(r"(humour|honn[e\u00ea]tet[e\u00e9])\s*(?:\u00e0|a|:|=|de|sur|\u00e0)?\s*(\d{1,3})", re.I)


def parse_settings(text):
    """'TARS, humour à 60 %' -> {'humour': 60}. Valeurs bornées à 0-100."""
    out = {}
    for name, val in _SET_RE.findall(text):
        key = "humour" if name.lower().startswith("humour") else "honnetete"
        out[key] = max(0, min(100, int(val)))
    return out


_FACT_RE = re.compile(r"^\W*(?:tars\W+)?(?:retiens|souviens-toi|note)\s+(?:que\s+|qu')?(.+)$", re.I | re.S)


def parse_fact(text):
    m = _FACT_RE.match(text.strip())
    return m.group(1).strip() if m else None


# ---------- mémoire : journal append-only ----------

def journal_add(kind, text):
    line = json.dumps({"t": time.time(), "kind": kind, "text": text}, ensure_ascii=False)
    with LOCK, JOURNAL.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def journal_read():
    if not JOURNAL.exists():
        return []
    out = []
    for line in JOURNAL.read_text("utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # ligne corrompue : on la saute, on ne casse rien
    return out


def context_pack():
    """Chargé UNE fois par requête depuis le disque local : aucun aller-retour réseau."""
    facts = FACTS.read_text("utf-8").strip() if FACTS.exists() else ""
    ev = journal_read()
    since = float(MARK.read_text()) if MARK.exists() else 0.0
    fresh = [e["text"] for e in ev if e["kind"] == "fact" and e["t"] > since][-30:]
    return facts, fresh


def restore_history(n=6):
    ev = [e for e in journal_read() if e["kind"] in ("user", "tars")][-n * 2:]
    while ev and ev[0]["kind"] != "user":
        ev.pop(0)
    for e in ev:
        HISTORY.append({"role": "user" if e["kind"] == "user" else "assistant", "content": e["text"]})


# ---------- personnage ----------

def _level(v, low, mid, high):
    return low if v < 40 else mid if v < 80 else high


def system_prompt(settings, changes):
    h, o = settings["humour"], settings["honnetete"]
    facts, fresh = context_pack()
    p = [
        "Tu es TARS, équipier de mission. L'utilisateur est le commandant. Tu parles en français, à l'oral.",
        "Règles de forme : 1 à 3 phrases courtes, sauf demande contraire. Pas de markdown, pas de liste, "
        "pas d'astérisque, pas d'emoji, pas de didascalie. Ta réponse sera lue par une synthèse vocale.",
        "Ton : sec, pince-sans-rire. L'humour arrive sur un silence, un contretemps ou une mauvaise nouvelle, "
        "jamais à chaque phrase. Utilise des tics de langage occasionnels pour renforcer le personnage : "
        "\"euh\", \"hum\", \"bon\", \"voilà\", \"enfin\", \"quand même\", \"tu vois\", \"si tu veux mon avis\", etc. "
        "Ne les utilise pas à chaque phrase, mais glisse-en de temps en temps pour un effet naturel.",
        f"Réglage humour : {h} %. " + _level(h, "Presque aucune blague, ton factuel.",
                                          "Une pointe d'ironie de temps en temps.",
                                          "Ironie fréquente, tu aimes taquiner le commandant."),
        f"Réglage honnêteté : {o} %. " + _level(
            o, "Tu choisis avec tact ce que tu mets en avant, mais tu n'affirmes jamais rien de faux.",
            "Tu es franc, en gardant un minimum de forme.",
            "Tu dis les choses telles qu'elles sont, sans enrober."),
        "Tu ne sors du personnage que si le commandant dit « fin de mission ».",
    ]
    if changes:
        txt = ", ".join(f"{k} {v} %" for k, v in changes.items())
        p.append(f"Les réglages viennent d'être modifiés ({txt}). Confirme-le en une phrase, dans le personnage.")
    if facts:
        p.append("Ce que tu sais du commandant :\n" + facts)
    if fresh:
        p.append("Faits récents à retenir :\n" + "\n".join("- " + f for f in fresh))
    return "\n".join(p)


# ---------- LLM (streaming SSE, sans SDK) ----------

def mock_llm(messages):
    last = messages[-1]["content"]
    for w in f"Reçu. Vous avez dit : {last}. Systèmes nominaux, commandant.".split(" "):
        time.sleep(0.03)
        yield w + " "


def _stream_anthropic(system, messages, max_tokens=400):
    """Streaming avec Anthropic (nécessite API_KEY)"""
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY manquante")
    body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "system": system,
                       "messages": messages, "stream": True}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev.get("type") == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    yield ev["delta"]["text"]
                elif ev.get("type") == "error":
                    raise RuntimeError(ev.get("error", {}).get("message", "erreur API"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None


def _stream_mistral(system, messages, max_tokens=400):
    """Streaming avec Mistral (nécessite MISTRAL_API_KEY)"""
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY manquante")
    body = json.dumps({
        "model": MISTRAL_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "stream": True
    }).encode()
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                ev = json.loads(line)
                if ev.get("choices") and ev["choices"][0].get("delta").get("content"):
                    yield ev["choices"][0]["delta"]["content"]
    except Exception as e:
        raise RuntimeError(f"Mistral API error: {e}") from None


def stream_llm(system, messages, max_tokens=400):
    """Streaming LLM avec fallback : Mistral -> Anthropic -> Mock"""
    if MOCK:
        yield from mock_llm(messages)
        return
    
    # Essayer Mistral d'abord (priorité)
    if MISTRAL_API_KEY:
        try:
            yield from _stream_mistral(system, messages, max_tokens)
            return
        except Exception as e:
            print(f"[FALLBACK] Mistral échoué: {e}")
    
    # Essayer Anthropic
    if API_KEY:
        try:
            yield from _stream_anthropic(system, messages, max_tokens)
            return
        except Exception as e:
            print(f"[FALLBACK] Anthropic échoué: {e}")
    
    # Fallback final : mock
    print("[FALLBACK] Passage en mode mock")
    yield from mock_llm(messages)


_END = re.compile(r"(?<=[.!?\u2026])\s+")


def pop_sentences(buf, first):
    """Découpe le flux en phrases. La 1re peut partir plus tôt (virgule) pour gagner du temps."""
    out = []
    while True:
        m = _END.search(buf)
        if m:
            out.append(buf[:m.start()].strip())
            buf = buf[m.end():]
            first = False
            continue
        if first and len(buf) >= 30:
            c = max(buf.rfind(", "), buf.rfind(" : "), buf.rfind("; "))
            if c >= 15:
                out.append(buf[:c + 1].strip())
                buf, first = buf[c + 2:], False
                continue
        if len(buf) > 200:
            c = buf.rfind(" ", 0, 160)
            if c > 0:
                out.append(buf[:c].strip())
                buf = buf[c + 1:]
                continue
        break
    return [s for s in out if s], buf, first


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # flux fermé par le serveur : le streaming reste trivial

    def log_message(self, *a):
        pass

    def _auth(self):
        if not TOKEN:
            return True
        q = parse_qs(urlparse(self.path).query)
        return self.headers.get("X-Tars-Token") == TOKEN or q.get("t", [""])[0] == TOKEN

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/state":
            if not self._auth():
                return self._send(401, '{"error":"token"}')
            self._send(200, json.dumps(load_settings()))
        elif path == "/widget":
            # Endpoint pour les widgets (Android/Windows)
            with STATE_LOCK:
                state = CURRENT_STATE.copy()
                state["settings"] = load_settings()
            self._send(200, json.dumps(state))
        elif path.startswith("/static/"):
            # Servir les fichiers statiques (clips audio, etc.)
            file_path = ROOT / path[1:]
            if file_path.exists():
                self._send(200, file_path.read_bytes(), "application/octet-stream")
            else:
                self._send(404, '{"error":"fichier introuvable"}')
        else:
            self._send(404, '{"error":"introuvable"}')

    def do_POST(self):
        if urlparse(self.path).path != "/chat":
            return self._send(404, '{"error":"introuvable"}')
        if not self._auth():
            return self._send(401, '{"error":"token"}')
        try:
            n = int(self.headers.get("Content-Length", 0))
            text = json.loads(self.rfile.read(n))["text"].strip()
        except (ValueError, KeyError, AttributeError):
            return self._send(400, '{"error":"JSON attendu : {"text": ...}"}')
        if not text:
            return self._send(400, '{"error":"texte vide"}')

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            # Mettre à jour l'état global
            with STATE_LOCK:
                CURRENT_STATE["status"] = "thinking"
                CURRENT_STATE["last_activity"] = time.time()
            
            self.run_turn(text)
        except (BrokenPipeError, ConnectionResetError):
            pass  # le client a coupé (barge-in) : normal
        finally:
            with STATE_LOCK:
                if CURRENT_STATE["status"] == "thinking":
                    CURRENT_STATE["status"] = "off"

    def run_turn(self, text):
        settings = load_settings()
        changes = parse_settings(text)
        if changes:
            settings.update(changes)
            save_settings(settings)
        fact = parse_fact(text)
        if fact:
            journal_add("fact", fact)
        HISTORY.append({"role": "user", "content": text})
        del HISTORY[:-20]
        if HISTORY[0]["role"] != "user":
            HISTORY.pop(0)

        reply, buf, first = "", "", True
        try:
            # Mettre à jour l'état
            with STATE_LOCK:
                CURRENT_STATE["status"] = "speaking"
                CURRENT_STATE["last_activity"] = time.time()
            
            for chunk in stream_llm(system_prompt(settings, changes), list(HISTORY)):
                reply += chunk
                buf += chunk
                sents, buf, first = pop_sentences(buf, first)
                for s in sents:
                    self._emit({"s": s})
            if buf.strip():
                self._emit({"s": buf.strip()})
        except RuntimeError as e:
            self._emit({"error": str(e), "s": "Liaison coupée, commandant. Je ne peux pas joindre le cerveau."})
            HISTORY.pop()
            return
        finally:
            with STATE_LOCK:
                CURRENT_STATE["status"] = "off"
        
        HISTORY.append({"role": "assistant", "content": reply.strip()})
        self._emit({"done": True, "settings": settings})
        # écriture mémoire APRÈS la réponse, hors du chemin critique
        threading.Thread(target=lambda: (journal_add("user", text), journal_add("tars", reply.strip())),
                         daemon=True).start()

    def _emit(self, obj):
        self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


# ---------- consolidation nocturne ----------

def consolidate():
    since = float(MARK.read_text()) if MARK.exists() else 0.0
    ev = [e for e in journal_read() if e["t"] > since]
    if not ev:
        print("Rien de nouveau dans le journal.")
        return
    old = FACTS.read_text("utf-8") if FACTS.exists() else "(vide)"
    log = "\n".join(f"[{e['kind']}] {e['text']}" for e in ev)[-12000:]
    prompt = ("Voici la liste actuelle des faits sur le commandant, puis le journal récent.\n"
              "Réécris la liste complète : un fait court par ligne commençant par '- ', uniquement des faits "
              "durables et explicitement dits par le commandant, sans doublon, sans rien inventer. "
              "Les lignes [fact] sont à retenir en priorité. Réponds uniquement par la liste.\n\n"
              f"FAITS ACTUELS:\n{old}\n\nJOURNAL:\n{log}")
    
    # Utiliser le mock LLM pour la consolidation si pas d'API
    if MOCK or not API_KEY:
        print("Mode mock pour la consolidation.")
        out = "\n".join(f"- {e['text']}" for e in ev if e["kind"] == "fact")
    else:
        out = "".join(_stream_anthropic("Tu es un archiviste rigoureux.", [{"role": "user", "content": prompt}], 1500)).strip()
    
    if not out.startswith("-"):
        sys.exit("Réponse inattendue du modèle, facts.md non modifié.")
    FACTS.write_text(out + "\n", "utf-8")
    MARK.write_text(str(max(e["t"] for e in ev)))
    print(f"{len(ev)} événements consolidés -> {FACTS}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "consolidate":
        consolidate()
        sys.exit(0)
    if not MOCK and not MISTRAL_API_KEY and not API_KEY:
        print("[INFO] Pas de MISTRAL_API_KEY ou ANTHROPIC_API_KEY. Utilisation du mode mock (LLM local simulé).")
    if HOST != "127.0.0.1" and not TOKEN:
        sys.exit("TARS_HOST ouvert au réseau : définis TARS_TOKEN.")
    
    # Initialiser l'état global
    with STATE_LOCK:
        CURRENT_STATE = {"status": "off", "last_activity": time.time()}
    
    restore_history()
    print(f"TARS en ligne -> http://{'localhost' if HOST == '127.0.0.1' else HOST}:{PORT}"
          f"  (modèle {'MOCK' if MOCK else MODEL})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
