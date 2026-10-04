#!/usr/bin/env python3
"""TARS pas tars : serveur vocal-texte, 100% local, zéro dépendance (stdlib uniquement).

Lancer :   python3 Tars.py
Ouvrir :   http://localhost:8000   (localhost = contexte sécurisé, le micro marche)
Nuit :     python3 Tars.py consolidate     (journal -> faits propres)
Test :     TARS_MOCK=1 python3 Tars.py     (faux LLM, aucune clé nécessaire)

Variables d'environnement :
  TARS_TOKEN       : Token pour l'API (header X-Tars-Token)
  TARS_HOST        : Hôte (127.0.0.1 par défaut)
  TARS_PORT        : Port (8000 par défaut)
  TARS_DATA        : Dossier des données (./data par défaut)
  ANTHROPIC_API_KEY: Clé API Anthropic
  MISTRAL_API_KEY : Clé API Mistral
  TARS_MODEL       : Modèle Anthropic (claude-haiku-4-5-20251001)
  MISTRAL_MODEL    : Modèle Mistral (mistral-tiny)
  TARS_PROVIDERS   : Ordre des fournisseurs (mistral,anthropic)
  TARS_MOCK        : Mode mock (1 = activé)
"""

import hmac
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# ---------- Configuration ----------
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("TARS_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
STATIC = (ROOT / "static").resolve()
JOURNAL, FACTS, SETTINGS = DATA / "journal.jsonl", DATA / "facts.md", DATA / "settings.json"
MARK = DATA / "consolidated_until.txt"
FACTS_BAK = DATA / "facts.md.bak"

# Clés API
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = os.environ.get("TARS_MODEL", "claude-haiku-4-5-20251001")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "open-mistral-7b")
PROVIDERS = [p.strip() for p in os.environ.get("TARS_PROVIDERS", "mistral,anthropic").split(",") if p.strip()]

# Sécurité
TOKEN = os.environ.get("TARS_TOKEN", "")
HOST = os.environ.get("TARS_HOST", "127.0.0.1")
PORT = int(os.environ.get("TARS_PORT", "8000"))
MOCK = os.environ.get("TARS_MOCK") == "1"

# Limites
MAX_BODY = 16 * 1024
MAX_TEXT = 4000
STATE_TTL = 120
DOWN_FOR = 300
CONSOLIDATE_CHUNK = 12000

# ---------- État partagé ----------
STATUSES = ("off", "listening", "thinking", "speaking")
CURRENT_STATE = {"status": "off", "last_activity": 0.0}
STATE_LOCK = threading.Lock()

# Verrous
LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
HIST_LOCK = threading.Lock()

# Données
HISTORY = []
TURN_GEN = 0
_FACT_EVENTS = []


def set_status(st, from_client=False):
    with STATE_LOCK:
        CURRENT_STATE["status"] = st
        CURRENT_STATE["last_activity"] = time.time()


def widget_state():
    with STATE_LOCK:
        s = dict(CURRENT_STATE)
    if s["status"] != "off" and time.time() - s["last_activity"] > STATE_TTL:
        s["status"] = "off"
    s["settings"] = load_settings()
    return s


def _atomic_write(path, text):
    with FILE_LOCK:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, "utf-8")
        os.replace(tmp, path)


# ---------- Réglages persistants ----------

def load_settings():
    try:
        s = json.loads(SETTINGS.read_text("utf-8"))
        if not isinstance(s, dict):
            s = {}
    except (OSError, ValueError):
        s = {}
    
    def pct(key, default):
        try:
            return max(0, min(100, int(s.get(key, default))))
        except (TypeError, ValueError):
            return default
    
    return {"humour": pct("humour", 60), "honnetete": pct("honnetete", 90)}


def save_settings(s):
    _atomic_write(SETTINGS, json.dumps(s))


_SET_RE = re.compile(r"(humour|honn[e\u00ea]tet[e\u00e9])\s*(?:\u00e0|a|:|=|de|sur)?\s*(\d{1,3})", re.I)


def parse_settings(text):
    out = {}
    for name, val in _SET_RE.findall(text):
        key = "humour" if name.lower().startswith("humour") else "honnetete"
        out[key] = max(0, min(100, int(val)))
    return out


_FACT_RE = re.compile(r"^\W*(?:tars\W+)?(?:retiens|souviens-toi|note)\s+(?:que\s+|qu')?(.+)$", re.I | re.S)


def parse_fact(text):
    m = _FACT_RE.match(text.strip())
    return m.group(1).strip() if m else None


# ---------- Mémoire : journal append-only ----------

def journal_add(kind, text):
    now = time.time()
    line = json.dumps({"t": now, "kind": kind, "text": text}, ensure_ascii=False)
    with LOCK:
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if kind == "fact":
            _FACT_EVENTS.append((now, text))


def journal_read():
    if not JOURNAL.exists():
        return []
    out = []
    for line in JOURNAL.read_text("utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("t"), (int, float)) \
                and isinstance(e.get("kind"), str) and isinstance(e.get("text"), str):
            out.append(e)
    return out


def load_fact_events():
    with LOCK:
        _FACT_EVENTS[:] = [(e["t"], e["text"]) for e in journal_read() if e["kind"] == "fact"]


def read_mark():
    try:
        return float(MARK.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def context_pack():
    try:
        facts = FACTS.read_text("utf-8").strip()
    except OSError:
        facts = ""
    since = read_mark()
    with LOCK:
        fresh = [t for (ts, t) in _FACT_EVENTS if ts > since][-30:]
    return facts, fresh


# ---------- Historique de session (thread-safe) ----------

def normalize(msgs):
    out = []
    for m in msgs:
        c = (m.get("content") or "").strip()
        if not c:
            continue
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n" + c}
        else:
            out.append({"role": m["role"], "content": c})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def restore_history(n=6):
    ev = [e for e in journal_read() if e["kind"] in ("user", "tars")][-n * 2:]
    msgs = [{"role": "user" if e["kind"] == "user" else "assistant", "content": e["text"]} for e in ev]
    with HIST_LOCK:
        HISTORY[:] = normalize(msgs)


def begin_turn(text):
    global TURN_GEN
    with HIST_LOCK:
        TURN_GEN += 1
        prev = list(HISTORY)
        HISTORY[:] = normalize(HISTORY + [{"role": "user", "content": text}])[-20:]
        while HISTORY and HISTORY[0]["role"] != "user":
            HISTORY.pop(0)
        return TURN_GEN, prev, list(HISTORY)


def is_current(gen):
    return gen == TURN_GEN


def finish_turn(gen, reply):
    with HIST_LOCK:
        if gen != TURN_GEN:
            return False
        if reply:
            HISTORY.append({"role": "assistant", "content": reply})
        return True


def rollback(gen, prev):
    with HIST_LOCK:
        if gen == TURN_GEN:
            HISTORY[:] = prev


# ---------- Personnage ----------

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
        '"euh", "hum", "bon", "voilà", "enfin", "quand même", "tu vois", "si tu veux mon avis", etc. '
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
    """Mode mock amélioré : répond comme TARS sans API."""
    last = messages[-1]["content"]
    
    # Réponses simples basées sur le contenu
    text_lower = last.lower()
    
    if any(greet in text_lower for greet in ["coucou", "salut", "bonjour", "hello", "hey"]):
        response = f"Bonjour, commandant. Systèmes nominaux."
    elif any(thanks in text_lower for thanks in ["merci", "thank", "thanks"]):
        response = f"De rien, commandant. Je suis là pour ça."
    elif any(bye in text_lower for bye in ["au revoir", "bye", "ciao", "à plus"]):
        response = f"À vos ordres, commandant. Fin de transmission."
    elif any(test in text_lower for test in ["test", "test test", "allô", "allo"]):
        response = f"Reçu. Tout est opérationnel."
    elif any(math in text_lower for math in ["math", "maths", "mathématique", "calcul"]):
        response = f"Les maths, c'est comme la gravité : ça marche, même si on ne comprend pas toujours pourquoi."
    elif "fin de mission" in text_lower:
        response = f"Fin de mission confirmée. À la prochaine, commandant."
    elif "comment ça va" in text_lower or "ça va" in text_lower:
        response = f"Systèmes à 100%. Et vous, commandant ?"
    elif "quoi" in text_lower or "comment" in text_lower:
        response = f"Je suis TARS, votre assistant. Que puis-je faire pour vous ?"
    elif any(question in text_lower for question in ["qui es tu", "qui êtes vous", "c'est quoi"]):
        response = f"Je suis TARS. Équipier de mission. À votre service, commandant."
    else:
        # Réponse générique avec des tics de langage
        tics = ["euh", "hum", "bon", "voilà", "enfin", "quand même", "tu vois", "si tu veux mon avis"]
        import random
        tic = random.choice(tics) if random.random() < 0.3 else ""
        response = f"Reçu. {tic}".strip()
        if tic:
            response += " " + last.capitalize() + "."
        else:
            response = f"Reçu. Vous avez dit : {last}. Systèmes nominaux, commandant."
    
    for w in response.split(" "):
        time.sleep(0.03)
        yield w + " "


def _stream_anthropic(system, messages, max_tokens=400):
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
                try:
                    ev = json.loads(line[5:])
                except ValueError:
                    continue
                kind = ev.get("type")
                if kind == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                    txt = ev["delta"].get("text", "")
                    if txt:
                        yield txt
                elif kind == "error":
                    raise RuntimeError((ev.get("error") or {}).get("message", "erreur API"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Anthropic {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Anthropic: {e}") from None


def _stream_mistral(system, messages, max_tokens=400):
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY manquante")
    body = json.dumps({
        "model": MISTRAL_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except ValueError:
                    continue
                choices = ev.get("choices") or []
                delta = (choices[0].get("delta") or {}) if choices else {}
                content = delta.get("content")
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if content:
                    yield content
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Mistral {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Mistral: {e}") from None


_STREAMS = {"mistral": _stream_mistral, "anthropic": _stream_anthropic}
_DOWN = {}


def _has_key(name):
    return bool(MISTRAL_API_KEY) if name == "mistral" else bool(API_KEY) if name == "anthropic" else False


def stream_llm(system, messages, max_tokens=400, providers=None):
    if MOCK:
        yield from mock_llm(messages)
        return
    names = [p for p in (providers or PROVIDERS) if p in _STREAMS and _has_key(p)]
    if not names:
        raise RuntimeError("Aucune clé API configurée (MISTRAL_API_KEY / ANTHROPIC_API_KEY).")
    now = time.time()
    names.sort(key=lambda n: _DOWN.get(n, 0) > now)
    errors = []
    for name in names:
        started = False
        try:
            for chunk in _STREAMS[name](system, messages, max_tokens):
                started = True
                yield chunk
            _DOWN.pop(name, None)
            return
        except RuntimeError as e:
            if started:
                raise
            _DOWN[name] = time.time() + DOWN_FOR
            print(f"[LLM] {name} indisponible : {e}", file=sys.stderr)
            errors.append(f"{name}: {e}")
    raise RuntimeError("Tous les fournisseurs ont échoué. " + " | ".join(errors))


_END = re.compile(r"(?<=[.!?\u2026])\s+")


def pop_sentences(buf, first):
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
    protocol_version = "HTTP/1.0"
    server_version = "TARS"

    def log_message(self, *a):
        pass

    def _auth(self):
        if not TOKEN and HOST != "127.0.0.1":
            return True
        got = self.headers.get("X-Tars-Token", "")
        return hmac.compare_digest(got.encode("utf-8"), TOKEN.encode("utf-8"))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, code, msg):
        self._send(code, json.dumps({"error": msg}, ensure_ascii=False))

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = -1
        if n <= 0:
            self._err(400, "corps JSON attendu")
            return None
        if n > MAX_BODY:
            self._err(413, "corps trop gros")
            return None
        try:
            data = json.loads(self.rfile.read(n))
        except ValueError:
            self._err(400, "JSON invalide")
            return None
        if not isinstance(data, dict):
            self._err(400, "objet JSON attendu")
            return None
        return data

    def _serve_static(self, url_path):
        """Sert UNIQUEMENT des fichiers sous static/ (pas de path traversal)."""
        rel = unquote(url_path[len("/static/"):])
        # Résolution du chemin et vérification qu'il reste sous STATIC
        try:
            target = (STATIC / rel).resolve()
        except (OSError, ValueError):
            return self._err(404, "introuvable")
        # Vérifier que target est bien dans STATIC
        if STATIC not in target.parents or not target.is_file():
            return self._err(404, "introuvable")
        # Bloquer les fichiers cachés (ex: .env)
        if any(part.startswith(".") for part in target.relative_to(STATIC).parts):
            return self._err(404, "introuvable")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            try:
                body = (ROOT / "index.html").read_bytes()
            except OSError:
                return self._err(404, "index.html introuvable")
            self._send(200, body, "text/html; charset=utf-8")
        elif path == "/state":
            if not self._auth():
                return self._err(401, "token")
            self._send(200, json.dumps(load_settings()))
        elif path == "/widget":
            # Endpoint public pour les widgets (statut et réglages uniquement)
            self._send(200, json.dumps(widget_state()))
        elif path.startswith("/static/"):
            self._serve_static(path)
        else:
            self._err(404, "introuvable")

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/chat", "/status"):
            return self._err(404, "introuvable")
        if not self._auth():
            return self._err(401, "token")
        data = self._read_json()
        if data is None:
            return

        if path == "/status":
            st = data.get("status")
            if st not in STATUSES:
                return self._err(400, "état invalide")
            set_status(st, from_client=True)
            self._send(200, json.dumps({"status": "ok"}))
            return

        # Gestion de /chat
        text = (data.get("text") or "").strip()
        if not text:
            return self._err(400, "texte vide")
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT]

        set_status("thinking")
        gen, prev, messages = begin_turn(text)

        # Initialiser la réponse HTTP pour le streaming SSE
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tars-Token")
        self.end_headers()

        reply, buf, first = "", "", True
        try:
            settings = load_settings()
            changes = parse_settings(text)
            if changes:
                settings.update(changes)
                save_settings(settings)
            fact = parse_fact(text)
            if fact:
                journal_add("fact", fact)

            for chunk in stream_llm(system_prompt(settings, changes), messages):
                reply += chunk
                buf += chunk
                sents, buf, first = pop_sentences(buf, first)
                for s in sents:
                    self._emit({"s": s})
            if buf.strip():
                self._emit({"s": buf.strip()})
        except RuntimeError as e:
            rollback(gen, prev)
            try:
                self._emit({"error": str(e), "s": "Liaison coupée, commandant. Je ne peux pas joindre le cerveau."})
            except ConnectionError:
                pass  # Client déjà déconnecté
            return
        except Exception as e:
            rollback(gen, prev)
            try:
                self._emit({"error": f"Erreur interne : {e}", "s": "Erreur critique, commandant."})
            except ConnectionError:
                pass  # Client déjà déconnecté
            return

        if not finish_turn(gen, reply):
            return  # un tour plus récent a pris la main

        set_status("off")
        try:
            self._emit({"done": True, "settings": settings})
        except ConnectionError:
            pass  # Client déjà déconnecté
        # Écriture mémoire APRÈS la réponse, hors du chemin critique
        threading.Thread(
            target=lambda: (journal_add("user", text), journal_add("tars", reply.strip())),
            daemon=True
        ).start()

    def _emit(self, obj):
        """Émet un événement SSE. Gère les déconnexions client."""
        try:
            data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            self.wfile.write(data)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client déconnecté, on arrête proprement
            raise ConnectionError("Client déconnecté") from None


# ---------- Consolidation nocturne ----------

def consolidate():
    since = read_mark()
    ev = [e for e in journal_read() if e["t"] > since and e["kind"] == "fact"]
    if not ev:
        print("Rien de nouveau dans le journal.")
        return
    try:
        old = FACTS.read_text("utf-8")
    except OSError:
        old = ""
    
    # Préparer le log des nouveaux faits
    log = "\n".join(f"[{e['kind']}] {e['text']}" for e in ev)
    
    # Si on a Mistral ou Anthropic, utiliser l'API pour consolider
    if MISTRAL_API_KEY:
        try:
            prompt = ("Voici la liste actuelle des faits sur le commandant, puis le journal récent.\n"
                     "Réécris la liste complète : un fait court par ligne commençant par '- ', uniquement des faits "
                     "durables et explicitement dits par le commandant, sans doublon, sans rien inventer. "
                     "Les lignes [fact] sont à retenir en priorité. Réponds uniquement par la liste.\n\n"
                     f"FAITS ACTUELS:\n{old}\n\nJOURNAL:\n{log}")
            out = "".join(_stream_mistral("Tu es un archiviste rigoureux.", [{"role": "user", "content": prompt}], CONSOLIDATE_CHUNK)).strip()
        except Exception as e:
            print(f"[CONSOLIDATE] Mistral échoué: {e}. Passage en mode manuel.")
            new_facts = "\n".join(f"- {e['text']}" for e in ev)
            out = old + ("\n" + new_facts if old.strip() else new_facts)
    elif API_KEY:
        try:
            prompt = ("Voici la liste actuelle des faits sur le commandant, puis le journal récent.\n"
                     "Réécris la liste complète : un fait court par ligne commençant par '- ', uniquement des faits "
                     "durables et explicitement dits par le commandant, sans doublon, sans rien inventer. "
                     "Les lignes [fact] sont à retenir en priorité. Réponds uniquement par la liste.\n\n"
                     f"FAITS ACTUELS:\n{old}\n\nJOURNAL:\n{log}")
            out = "".join(_stream_anthropic("Tu es un archiviste rigoureux.", [{"role": "user", "content": prompt}], CONSOLIDATE_CHUNK)).strip()
        except Exception as e:
            print(f"[CONSOLIDATE] Anthropic échoué: {e}. Passage en mode manuel.")
            new_facts = "\n".join(f"- {e['text']}" for e in ev)
            out = old + ("\n" + new_facts if old.strip() else new_facts)
    else:
        # Mode manuel : ajouter les nouveaux faits à l'ancien
        new_facts = "\n".join(f"- {e['text']}" for e in ev)
        out = old + ("\n" + new_facts if old else new_facts)
    
    if not out.startswith("-"):
        print("Réponse inattendue du modèle, facts.md non modifié.")
        return
    
    # Sauvegarde de sécurité
    if FACTS.exists():
        shutil.copy2(FACTS, FACTS_BAK)
    
    _atomic_write(FACTS, out + "\n")
    MARK.write_text(str(max(e["t"] for e in ev)))
    print(f"{len(ev)} événements consolidés -> {FACTS}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "consolidate":
        consolidate()
        sys.exit(0)
    
    if not MOCK and not any([MISTRAL_API_KEY, API_KEY]):
        print("Définis ANTHROPIC_API_KEY ou MISTRAL_API_KEY (ou TARS_MOCK=1 pour tester sans clé).")
        print("Exemple : MISTRAL_API_KEY=ta_clé python3 Tars.py")
        sys.exit(1)
    
    if HOST != "127.0.0.1" and not TOKEN:
        print("TARS_HOST ouvert au réseau : définis TARS_TOKEN.")
        sys.exit(1)
    
    restore_history()
    print(f"TARS en ligne -> http://{'localhost' if HOST == '127.0.0.1' else HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
