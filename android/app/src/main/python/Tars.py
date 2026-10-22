#!/usr/bin/env python3
"""TARS pas tars : serveur vocal-texte, 100% local, zéro dépendance (stdlib uniquement).

Lancer :   python3 Tars.py
Ouvrir :   http://localhost:8000   (localhost = contexte sécurisé, le micro marche)
Nuit :     python3 Tars.py consolidate     (journal -> faits propres)
Test :     TARS_MOCK=1 python3 Tars.py     (faux LLM, aucune clé nécessaire)

Variables d'environnement :
  TARS_TOKEN       : Token pour l'API (header X-Tars-Token ou cookie de session)
  TARS_BOOT_NONCE  : Nonce de bootstrap one-time (URL /?boot=<nonce>)
  TARS_HOST        : Hôte (127.0.0.1 par défaut)
  TARS_PORT        : Port (8000 par défaut, 0 = port aléatoire)
  TARS_DATA        : Dossier des données (./data par défaut)
  ANTHROPIC_API_KEY: Clé API Anthropic
  MISTRAL_API_KEY : Clé API Mistral
  GROQ_API_KEY : Clé API Groq
  TARS_MODEL       : Modèle Anthropic (claude-haiku-4-5-20251001)
  MISTRAL_MODEL    : Modèle Mistral (mistral-tiny)
  GROQ_MODEL    : Modèle Groq (openai/gpt-oss-120b)
  TARS_PROVIDERS   : Ordre des fournisseurs (groq,mistral,anthropic)
  TARS_MOCK        : Mode mock (1 = activé)

Bootstrap : ouvrir http://localhost:<port>/?boot=<TARS_BOOT_NONCE> une seule fois.
Le nonce est consommé et un cookie de session HttpOnly SameSite=Strict est posé.
"""

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# ---------- Configuration ----------
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("TARS_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
SESSION_FILE = DATA / "session.key"
try:
    os.chmod(DATA, 0o700)
except OSError:
    pass
mimetypes.add_type("font/woff2", ".woff2")  # Python < 3.11 ne le connaît pas
STATIC = (ROOT / "static").resolve()
JOURNAL, FACTS, SETTINGS = DATA / "journal.jsonl", DATA / "facts.md", DATA / "settings.json"
SECRETS = DATA / "secrets.json"
MARK = DATA / "consolidated_until.txt"
FACTS_BAK = DATA / "facts.md.bak"
FACTS_JSON = DATA / "facts.json"
FACTS_META = DATA / "facts.meta.json"
MEMORY_PROPOSALS = DATA / "memory_proposals.json"
HISTORY_FILE = DATA / "history.jsonl"
TTS_CACHE = DATA / "tts-cache"

# Clés API
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = os.environ.get("TARS_MODEL", "claude-haiku-4-5-20251001")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "open-mistral-7b")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
PROVIDERS = [p.strip() for p in os.environ.get("TARS_PROVIDERS", "groq,mistral,anthropic").split(",") if p.strip()]
PIPER_BIN = (os.environ.get("TARS_PIPER_BIN") or "piper").strip() or "piper"
PIPER_MODEL = (os.environ.get("TARS_PIPER_MODEL") or "").strip()

# Sécurité
TOKEN = (os.environ.get("TARS_TOKEN") or "").strip() or secrets.token_urlsafe(32)
BOOT_NONCE = (os.environ.get("TARS_BOOT_NONCE") or "").strip() or secrets.token_urlsafe(24)


def _load_session_token():
    """Relit le jeton de session persistant, ou en crée un nouveau."""
    try:
        token = SESSION_FILE.read_text("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        token = ""
    if re.fullmatch(r"[A-Za-z0-9_-]{20,128}", token):
        return token
    token = secrets.token_urlsafe(32)
    try:
        tmp = SESSION_FILE.with_name(SESSION_FILE.name + ".tmp")
        tmp.write_text(token, "utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, SESSION_FILE)
        try:
            os.chmod(SESSION_FILE, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return token


SESSION = _load_session_token()
HOST = os.environ.get("TARS_HOST", "127.0.0.1")
PORT = int(os.environ.get("TARS_PORT", "8000"))
MOCK = os.environ.get("TARS_MOCK") == "1"


def get_token():
    return TOKEN


def get_boot_nonce():
    return BOOT_NONCE

# Limites
MAX_BODY = 16 * 1024
MAX_AUDIO = 10 * 1024 * 1024
MAX_TEXT = 4000
MAX_FACT = 500
MAX_PROPOSAL = 240
MAX_TTS = 600
MEMORY_MAX = 200
PROPOSAL_PENDING_MAX = 12
PROPOSAL_HISTORY_MAX = 200
PROPOSAL_TTL = 14 * 24 * 60 * 60
TOMBSTONE_MAX = MEMORY_MAX * 4
TTS_CACHE_MAX = 200
STATE_TTL = 120
DOWN_FOR = 300
CONSOLIDATE_CHUNK = 8000
HISTORY_MAX_RECORDS = 5000

# STT Groq
STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"
_AUDIO_TYPES = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
}
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Tars/1.0"

mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("image/svg+xml", ".svg")

# ---------- État partagé ----------
STATUSES = ("off", "listening", "thinking", "speaking")
CURRENT_STATE = {"status": "off", "last_activity": 0.0}
STATE_LOCK = threading.Lock()

# Verrous
LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
HIST_LOCK = threading.Lock()
HISTORY_FILE_LOCK = threading.Lock()
MEM_LOCK = threading.Lock()
PROP_LOCK = threading.Lock()
ERROR_LOCK = threading.Lock()
TTS_LOCK = threading.Lock()

# Données
HISTORY = []
TURN_GEN = 0
CURRENT_SESSION = ""
_FACT_EVENTS = []
_LAST_ERROR = {"message": "", "at": 0.0, "source": ""}

_FACT_SOURCES = ("conversation", "manuel", "consolidation", "import")
_FACT_ID_RE = re.compile(r"^f_[0-9a-f]{12}$")
_PROPOSAL_ID_RE = re.compile(r"^p_[0-9a-f]{12}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def record_error(source, message):
    """Mémorise la dernière erreur, sans jamais exposer une clé API."""
    msg = str(message or "")
    for key in (GROQ_API_KEY, MISTRAL_API_KEY, API_KEY):
        if key:
            msg = msg.replace(key, "[clé masquée]")
    msg = msg.encode("utf-8", "replace").decode("utf-8")[:300]
    with ERROR_LOCK:
        _LAST_ERROR["message"] = msg
        _LAST_ERROR["at"] = time.time()
        _LAST_ERROR["source"] = str(source or "")[:40]


def last_error_snapshot():
    with ERROR_LOCK:
        return dict(_LAST_ERROR)


# ---------- Secrets persistants ----------
_SECRET_FIELDS = ("groq_api_key", "mistral_api_key", "anthropic_api_key", "groq_model")


def load_secrets():
    """Charge secrets.json en écrasant les globals, sauf si l'env est défini (priorité)."""
    global GROQ_API_KEY, MISTRAL_API_KEY, API_KEY, GROQ_MODEL
    try:
        d = json.loads(SECRETS.read_text("utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(d, dict):
        return
    if not os.environ.get("GROQ_API_KEY") and isinstance(d.get("groq_api_key"), str):
        GROQ_API_KEY = d["groq_api_key"].strip()
    if not os.environ.get("MISTRAL_API_KEY") and isinstance(d.get("mistral_api_key"), str):
        MISTRAL_API_KEY = d["mistral_api_key"].strip()
    if not os.environ.get("ANTHROPIC_API_KEY") and isinstance(d.get("anthropic_api_key"), str):
        API_KEY = d["anthropic_api_key"].strip()
    if not os.environ.get("GROQ_MODEL") and isinstance(d.get("groq_model"), str) and d["groq_model"].strip():
        GROQ_MODEL = d["groq_model"].strip()


def save_secrets(d):
    """Fusionne les champs connus dans secrets.json (écriture atomique)."""
    current = {}
    try:
        old = json.loads(SECRETS.read_text("utf-8"))
        if isinstance(old, dict):
            current = {k: v for k, v in old.items() if k in _SECRET_FIELDS}
    except (OSError, ValueError):
        pass
    for k in _SECRET_FIELDS:
        if k in d:
            current[k] = d[k]
    _atomic_write(SECRETS, json.dumps(current, ensure_ascii=False, indent=2) + "\n")


def config_snapshot():
    return {
        "has_groq": bool(GROQ_API_KEY),
        "has_mistral": bool(MISTRAL_API_KEY),
        "has_anthropic": bool(API_KEY),
        "groq_model": GROQ_MODEL,
    }


# Au chargement : les secrets du fichier complètent l'environnement.
# (indispensable pour le lanceur Android qui importe Tars sans passer par __main__)
load_secrets()


# ---------- Réglages persistants ----------

DESIGNS = ("monolithe", "editorial")
DEFAULT_DESIGN = "monolithe"


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

    design = s.get("design")
    if design not in DESIGNS:
        design = DEFAULT_DESIGN

    return {"humour": pct("humour", 60), "honnetete": pct("honnetete", 90), "design": design}


def save_settings(s):
    _atomic_write(SETTINGS, json.dumps(s))


_HTML_FR_RE = re.compile(r'<html\b[^>]*\blang=(["\'])fr\1[^>]*>', re.I)
_DATA_DESIGN_RE = re.compile(r'\s+data-design=(["\']).*?\1', re.I)


def inject_design(html, design):
    """Injecte data-design dans la première balise <html lang="fr"> (whitelist stricte)."""
    if design not in DESIGNS:
        design = DEFAULT_DESIGN
    match = _HTML_FR_RE.search(html)
    if not match:
        return html
    tag = _DATA_DESIGN_RE.sub("", match.group(0))
    new_tag = tag[:-1] + f' data-design="{design}">'
    return html[:match.start()] + new_tag + html[match.end():]


_SET_RE = re.compile(r"(humour|honn[e\u00ea]te(?:t[e\u00e9])?)\s*(?:\u00e0|a|:|=|de|sur)?\s*(\d{1,3})", re.I)
_SET_INTENT_RE = re.compile(r"tars|regle|r\u00e8gle|mets?|passe|change|remet", re.I)


def parse_settings(text):
    if not _SET_INTENT_RE.search(text):
        return {}
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
        try:
            os.chmod(JOURNAL, 0o600)
        except OSError:
            pass
        if kind == "fact":
            _FACT_EVENTS.append((now, text))
    if kind == "fact":
        try:
            memory_add(text, "conversation")
        except (OSError, UnicodeError) as e:
            print(f"[MEMORY] écriture des faits impossible : {e}", file=sys.stderr)


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


# ---------- Mémoire structurée (facts.json, source de vérité) ----------

def _new_fact_id():
    return "f_" + secrets.token_hex(6)


def _valid_fact_id(fid):
    return isinstance(fid, str) and _FACT_ID_RE.fullmatch(fid) is not None


def _clean_fact_text(text):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if "\n" in text or "\r" in text:
        text = " ".join(text.split())
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if not text or len(text) > MAX_FACT:
        return None
    return text


def _fact_created(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return time.time()
    # Rejette NaN et les dates aberrantes.
    if not (0 < value < 4102444800):
        return time.time()
    return float(value)


def _tombstone_key(text):
    cleaned = _clean_fact_text(text)
    return cleaned.lower() if cleaned is not None else None


def _load_facts_meta():
    try:
        doc = json.loads(FACTS_META.read_text("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        doc = None
    meta = {"tombstones": [], "cleared_at": 0.0}
    if not isinstance(doc, dict):
        return meta
    cleared = doc.get("cleared_at")
    if isinstance(cleared, (int, float)) and not isinstance(cleared, bool):
        if 0 <= cleared < 4102444800:
            meta["cleared_at"] = float(cleared)
    raw = doc.get("tombstones")
    if isinstance(raw, list):
        seen = set()
        for entry in raw:
            key = _tombstone_key(entry)
            if key is None or key in seen:
                continue
            seen.add(key)
            meta["tombstones"].append(key)
        meta["tombstones"] = meta["tombstones"][-TOMBSTONE_MAX:]
    return meta


def _save_facts_meta(meta):
    doc = {
        "tombstones": list(meta["tombstones"])[-TOMBSTONE_MAX:],
        "cleared_at": float(meta["cleared_at"]),
    }
    _atomic_write(FACTS_META, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _tombstone_add(meta, text):
    key = _tombstone_key(text)
    if key is None:
        return
    tombstones = [item for item in meta["tombstones"] if item != key]
    tombstones.append(key)
    meta["tombstones"] = tombstones[-TOMBSTONE_MAX:]


def _tombstone_discard(meta, text):
    key = _tombstone_key(text)
    if key is None:
        return
    meta["tombstones"] = [item for item in meta["tombstones"] if item != key]


def _without_tombstones(items):
    tombstones = set(_load_facts_meta()["tombstones"])
    if not tombstones:
        return items
    return [item for item in items if item["text"].lower() not in tombstones]


def _sanitize_fact_items(raw):
    out, seen, ids = [], set(), set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = _clean_fact_text(entry.get("text"))
        if text is None:
            continue
        key = text.lower()
        if key in seen:
            continue
        fid = entry.get("id")
        if not _valid_fact_id(fid) or fid in ids:
            seed = "fact:" + key
            fid = "f_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
            while fid in ids:
                seed += "#"
                fid = "f_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        source = entry.get("source")
        if source not in _FACT_SOURCES:
            source = "import"
        out.append({
            "id": fid,
            "text": text,
            "created": _fact_created(entry.get("created")),
            "source": source,
        })
        ids.add(fid)
        seen.add(key)
        if len(out) >= MEMORY_MAX:
            break
    return out


def _facts_header():
    try:
        for line in FACTS.read_text("utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped
    except OSError:
        pass
    return "# Faits sur le commandant"


def _facts_md_text(items):
    lines = [_facts_header()]
    if items:
        lines.append("")
        lines.extend("- " + item["text"] for item in items)
    return "\n".join(lines) + "\n"


def _import_facts_md():
    try:
        raw = FACTS.read_text("utf-8", errors="replace")
    except OSError:
        return []
    now = time.time()
    out, seen, ids = [], set(), set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        text = stripped[2:].strip()[:MAX_FACT]
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        fid = _new_fact_id()
        while fid in ids:
            fid = _new_fact_id()
        ids.add(fid)
        out.append({"id": fid, "text": text, "created": now, "source": "import"})
        if len(out) >= MEMORY_MAX:
            break
    return out


def _write_memory(items):
    _atomic_write(FACTS_JSON, json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(FACTS, _facts_md_text(items))


def _load_facts_locked():
    try:
        doc = json.loads(FACTS_JSON.read_text("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        doc = None
    if isinstance(doc, dict) and isinstance(doc.get("items"), list):
        return _sanitize_fact_items(doc["items"])
    items = _without_tombstones(_import_facts_md())
    try:
        _write_memory(items)
    except (OSError, UnicodeError):
        pass
    return items


def memory_items():
    """Retourne les faits structurés, sans jamais lever sur un fichier absent/corrompu."""
    with MEM_LOCK:
        return [dict(item) for item in _load_facts_locked()]


def memory_add(text, source="manuel"):
    cleaned = _clean_fact_text(text)
    if cleaned is None:
        return None
    if source not in _FACT_SOURCES:
        source = "manuel"
    with MEM_LOCK:
        meta = _load_facts_meta()
        items = _load_facts_locked()
        key = cleaned.lower()
        for item in items:
            if item["text"].lower() == key:
                if key in meta["tombstones"]:
                    _tombstone_discard(meta, cleaned)
                    _save_facts_meta(meta)
                return dict(item)
        used = {existing["id"] for existing in items}
        fid = _new_fact_id()
        while fid in used:
            fid = _new_fact_id()
        item = {
            "id": fid,
            "text": cleaned,
            "created": time.time(),
            "source": source,
        }
        items.append(item)
        if len(items) > MEMORY_MAX:
            items = items[-MEMORY_MAX:]
        _write_memory(items)
        if key in meta["tombstones"]:
            _tombstone_discard(meta, cleaned)
            _save_facts_meta(meta)
        return dict(item)


def memory_update(fid, text):
    cleaned = _clean_fact_text(text)
    if not _valid_fact_id(fid) or cleaned is None:
        return None
    with MEM_LOCK:
        meta = _load_facts_meta()
        items = _load_facts_locked()
        index = None
        for i, item in enumerate(items):
            if item["id"] == fid:
                index = i
                break
        if index is None:
            return None
        key = cleaned.lower()
        for i, item in enumerate(items):
            if i != index and item["text"].lower() == key:
                return None
        old_text = items[index]["text"]
        items[index]["text"] = cleaned
        _write_memory(items)
        _tombstone_add(meta, old_text)
        _tombstone_discard(meta, cleaned)
        _save_facts_meta(meta)
        return dict(items[index])


def memory_delete(fid):
    if not _valid_fact_id(fid):
        return False
    with MEM_LOCK:
        meta = _load_facts_meta()
        items = _load_facts_locked()
        target = next((item for item in items if item["id"] == fid), None)
        if target is None:
            return False
        _write_memory([item for item in items if item["id"] != fid])
        _tombstone_add(meta, target["text"])
        _save_facts_meta(meta)
        return True


def memory_clear():
    with MEM_LOCK:
        meta = _load_facts_meta()
        for item in _load_facts_locked():
            _tombstone_add(meta, item["text"])
        meta["cleared_at"] = time.time()
        _save_facts_meta(meta)
        _write_memory([])
    return True


def memory_export():
    items = memory_items()
    lines = ["# Mémoire TARS", ""]
    for item in items:
        try:
            date = datetime.fromtimestamp(item["created"], timezone.utc).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            date = ""
        lines.append("- {} ({}, {})".format(item["text"], item["source"], date))
    return "\n".join(lines) + "\n"


# ---------- Mémoire proposée (rien n'est écrit avant acceptation) ----------

def _new_proposal_id():
    return "p_" + secrets.token_hex(6)


def _valid_proposal_id(pid):
    return isinstance(pid, str) and _PROPOSAL_ID_RE.fullmatch(pid) is not None


def _clean_proposal_text(text):
    if not isinstance(text, str):
        return None
    cleaned = _clean_fact_text(text[:MAX_FACT])
    if cleaned is None:
        return None
    cleaned = cleaned[:MAX_PROPOSAL].strip()
    return cleaned or None


def _proposal_created(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return time.time()
    if not (0 < value < 4102444800):
        return time.time()
    return float(value)


def _sanitize_proposal_items(raw):
    now = time.time()
    out, ids, seen = [], set(), set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status not in ("pending", "accepted", "rejected"):
            continue
        text = _clean_proposal_text(entry.get("text"))
        if text is None:
            continue
        created = _proposal_created(entry.get("created"))
        if status == "pending" and now - created > PROPOSAL_TTL:
            continue
        key = text.lower()
        if key in seen:
            continue
        pid = entry.get("id")
        if not _valid_proposal_id(pid) or pid in ids:
            pid = _new_proposal_id()
            while pid in ids:
                pid = _new_proposal_id()
        item = {
            "id": pid,
            "text": text,
            "created": created,
            "status": status,
        }
        if status == "accepted":
            fid = entry.get("fact_id")
            if _valid_fact_id(fid):
                item["fact_id"] = fid
        elif status == "rejected":
            item["rejected_at"] = _proposal_created(entry.get("rejected_at"))
        out.append(item)
        ids.add(pid)
        seen.add(key)

    pending = sorted(
        (item for item in out if item["status"] == "pending"),
        key=lambda item: item["created"])
    if len(pending) > PROPOSAL_PENDING_MAX:
        keep = {item["id"] for item in pending[-PROPOSAL_PENDING_MAX:]}
        out = [item for item in out if item["status"] != "pending" or item["id"] in keep]

    history = sorted(
        (item for item in out if item["status"] != "pending"),
        key=lambda item: item["created"])
    if len(history) > PROPOSAL_HISTORY_MAX:
        drop = {item["id"] for item in history[:-PROPOSAL_HISTORY_MAX]}
        out = [item for item in out if item["id"] not in drop]
    return out


def _write_proposals(items):
    _atomic_write(
        MEMORY_PROPOSALS,
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n")


def _load_proposals_locked():
    try:
        doc = json.loads(MEMORY_PROPOSALS.read_text("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    raw = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(raw, list):
        return []
    items = _sanitize_proposal_items(raw)
    if raw != items:
        try:
            _write_proposals(items)
        except (OSError, UnicodeError):
            pass
    return items


def _public_proposal(item):
    return {"id": item["id"], "text": item["text"], "created": item["created"]}


def _pending_proposals_locked():
    return [_public_proposal(item) for item in _load_proposals_locked()
            if item["status"] == "pending"]


def pending_proposals():
    with PROP_LOCK:
        return _pending_proposals_locked()


def _proposal_known_keys(items):
    known = {item["text"].strip().lower() for item in memory_items()}
    known.update(_load_facts_meta()["tombstones"])
    for item in items:
        if item["status"] in ("pending", "rejected"):
            known.add(item["text"].lower())
    return known


_PROPOSAL_MARKERS = re.compile(
    r"(?:\bje\s+m['\u2019]?appelle\b|\bje\s+pr[ée]f[èe]re\b|\bj['\u2019]?aime\b|"
    r"\bj['\u2019]?adore\b|\bje\s+d[ée]teste\b|\bje\s+ne\s+supporte\s+pas\b|"
    r"\bj['\u2019]?utilise\b|\bje\s+travaille\b|"
    r"\bj['\u2019]?habite\b|\bje\s+vis\b|\bmon\s+projet\b|\bmon\s+m[ée]tier\b|"
    r"\bmon\s+objectif\b|\bma\s+machine\b|\bmes\s+outils\b|\bmon\s+[ée]quipe\b|"
    r"\bmon\s+entreprise\b|\bma\s+ville\b|\bmon\s+pays\b|\bma\s+langue\b|"
    r"\bmon\s+ordinateur\b|\bmon\s+budget\b|\bmes\s+horaires\b|\bje\s+d[ée]veloppe\b|"
    r"\bj['\u2019]?[ée]tudie\b|\bje\s+code\b|\bje\s+parle\b|\bje\s+m['\u2019]?entra[îi]ne\b|"
    r"\bje\s+suis\s+(?:d[ée]veloppeur(?:se)?|ing[ée]nieur(?:e)?|[ée]tudiant(?:e)?|"
    r"professeur|chercheur(?:se)?|consultant(?:e)?|freelance|ind[ée]pendant(?:e)?|"
    r"salari[ée](?:e)?|retrait[ée](?:e)?|p[èe]re|m[èe]re|mari[ée](?:e)?|c[ée]libataire|"
    r"bas[ée](?:e)?\s+[àa]|allergique)\b|"
    r"\bj['\u2019]?ai\s+\d{1,3}\s+ans\b|\bj['\u2019]?ai\s+besoin\b|"
    r"\bje\s+ne\s+peux\s+pas\b|\bmon\s+anniversaire\b)",
    re.I)
_PROPOSAL_SPLIT_RE = re.compile(r"(?<=[.!?\u2026])\s+|\n+")
_PROPOSAL_JSON_RE = re.compile(r"\{.*\}", re.S)


def _heuristic_proposals(text):
    if not isinstance(text, str):
        return []
    raw = text.strip()
    if len(raw) < 10 or parse_fact(raw):
        return []
    out, seen = [], set()
    for part in _PROPOSAL_SPLIT_RE.split(raw):
        sentence = part.strip()
        if len(sentence) < 10 or "?" in sentence:
            continue
        match = _PROPOSAL_MARKERS.search(sentence)
        if match is None:
            continue
        clause = sentence[match.start():].strip(" ,;:-")
        if len(clause) < 10:
            continue
        cleaned = _clean_proposal_text(clause)
        if cleaned is None or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        out.append(cleaned)
        if len(out) >= 2:
            break
    return out


_PROPOSAL_SYSTEM = (
    "Tu extrais la mémoire durable du commandant. Repère uniquement les faits durables et utiles "
    "sur lui : préférences, identité, projet, contraintes, outils, dates. Ignore le small talk, "
    "les questions et le temporaire. Réponds uniquement par un objet JSON valide de la forme "
    "{\"facts\": [\"...\"]}, avec 0 à 2 faits courts, sans texte hors JSON."
)


def _parse_proposal_payload(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        doc = json.loads(text)
    except ValueError:
        match = _PROPOSAL_JSON_RE.search(text)
        if match is None:
            return None
        try:
            doc = json.loads(match.group(0))
        except ValueError:
            return None
    if not isinstance(doc, dict) or not isinstance(doc.get("facts"), list):
        return None
    out, seen = [], set()
    for entry in doc["facts"][:2]:
        cleaned = _clean_proposal_text(entry)
        if cleaned is None or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        out.append(cleaned)
    return out


def _llm_proposals(text):
    raw = "".join(stream_llm(
        _PROPOSAL_SYSTEM,
        [{"role": "user", "content": text[:MAX_TEXT]}],
        max_tokens=180))
    return _parse_proposal_payload(raw)


def extract_memory_proposals(text):
    """Extrait 0 à 2 faits durables ; ne touche jamais facts.json."""
    if not isinstance(text, str):
        return []
    text = text.strip()
    if not text or parse_fact(text):
        return []
    if MOCK and not any([GROQ_API_KEY, MISTRAL_API_KEY, API_KEY]):
        return _heuristic_proposals(text)
    try:
        facts = _llm_proposals(text)
    except Exception as e:
        print(f"[PROPOSAL] extraction indisponible : {e}", file=sys.stderr)
        facts = None
    if facts is None:
        return _heuristic_proposals(text)
    return [fact for fact in facts if not parse_fact(fact)]


def proposals_create(texts):
    """Crée des propositions pending dédupliquées. Retourne (pending, créées)."""
    created = 0
    with PROP_LOCK:
        items = _load_proposals_locked()
        known = _proposal_known_keys(items)
        now = time.time()
        for raw in texts or []:
            text = _clean_proposal_text(raw)
            if text is None or text.lower() in known:
                continue
            used = {item["id"] for item in items}
            pid = _new_proposal_id()
            while pid in used:
                pid = _new_proposal_id()
            items.append({
                "id": pid,
                "text": text,
                "created": now,
                "status": "pending",
            })
            known.add(text.lower())
            created += 1
        if created:
            items = _sanitize_proposal_items(items)
            _write_proposals(items)
        pending = [_public_proposal(item) for item in items if item["status"] == "pending"]
    return pending, created


def proposals_decide(action, pid):
    """Accepte ou refuse une proposition pending.

    Rejouer une action sur un id déjà traité renvoie None (404) sans doublon :
    une acceptation crée au plus un fait, un refus reste bloquant.
    """
    with PROP_LOCK:
        items = _load_proposals_locked()
        index = next((i for i, item in enumerate(items)
                      if item["id"] == pid and item["status"] == "pending"), None)
        if index is None:
            return None
        fact = None
        if action == "reject":
            items[index]["status"] = "rejected"
            items[index].pop("fact_id", None)
            items[index]["rejected_at"] = time.time()
        else:
            fact = memory_add(items[index]["text"], "conversation")
            if fact is None:
                return {"invalid": True, "fact": None, "items": _pending_proposals_locked()}
            items[index]["status"] = "accepted"
            items[index]["fact_id"] = fact["id"]
            items[index].pop("rejected_at", None)
        items = _sanitize_proposal_items(items)
        _write_proposals(items)
        pending = [_public_proposal(item) for item in items if item["status"] == "pending"]
    return {"invalid": False, "fact": fact, "items": pending}


def sync_memory_from_lines(lines, expected_cleared_at=None):
    """Aligne facts.json sur les lignes de facts.md après consolidation."""
    with MEM_LOCK:
        meta = _load_facts_meta()
        if expected_cleared_at is not None and meta["cleared_at"] > expected_cleared_at:
            return None
        tombstones = set(meta["tombstones"])
        old_items = _load_facts_locked()
        by_text = {item["text"].strip().lower(): item for item in old_items}
        out, seen, ids, now = [], set(), set(), time.time()
        for raw in lines:
            stripped = raw.strip()
            if not stripped.startswith("-"):
                continue
            text = _clean_fact_text(stripped[1:].strip()[:MAX_FACT])
            if text is None:
                continue
            key = text.lower()
            if key in tombstones or key in seen:
                continue
            seen.add(key)
            old = by_text.get(key)
            if old is not None:
                out.append(dict(old))
                ids.add(old["id"])
            else:
                fid = _new_fact_id()
                while fid in ids:
                    fid = _new_fact_id()
                ids.add(fid)
                out.append({"id": fid, "text": text, "created": now, "source": "consolidation"})
            if len(out) >= MEMORY_MAX:
                break
        _write_memory(out)
        return out


def read_mark():
    try:
        return float(MARK.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def context_pack():
    items = memory_items()
    facts = "\n".join("- " + item["text"] for item in items)
    known = {item["text"].strip().lower() for item in items}
    with MEM_LOCK:
        meta = _load_facts_meta()
    tombstones = set(meta["tombstones"])
    cleared_at = meta["cleared_at"]
    since = read_mark()
    fresh = []
    with LOCK:
        events = [(ts, t) for (ts, t) in _FACT_EVENTS if ts > since and ts > cleared_at][-30:]
    for _, text in events:
        key = _tombstone_key(text)
        if key is None or key in tombstones or key in known:
            continue
        known.add(key)
        fresh.append(text)
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


def _valid_session_id(sid):
    return isinstance(sid, str) and _SESSION_RE.fullmatch(sid) is not None


def _read_history_locked():
    try:
        raw = HISTORY_FILE.read_text("utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session")
        stamp = rec.get("t")
        user = rec.get("user")
        assistant = rec.get("assistant")
        if not _valid_session_id(sid):
            continue
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            continue
        if not (0 < stamp < 4102444800):
            continue
        if not isinstance(user, str) or not isinstance(assistant, str):
            continue
        out.append({"session": sid, "t": float(stamp), "user": user, "assistant": assistant})
    return out


def history_records():
    with HISTORY_FILE_LOCK:
        return _read_history_locked()


def _messages_from_records(records, sid):
    out = []
    for rec in records:
        if rec["session"] != sid:
            continue
        if rec["user"].strip():
            out.append({"role": "user", "content": rec["user"].strip(), "t": rec["t"]})
        if rec["assistant"].strip():
            out.append({"role": "assistant", "content": rec["assistant"].strip(), "t": rec["t"]})
    return out


def history_messages(sid):
    if not _valid_session_id(sid):
        return []
    return _messages_from_records(history_records(), sid)


def _truncate(text, size):
    text = " ".join(text.split())
    return text[:size]


def history_sessions():
    sessions = {}
    for rec in history_records():
        sid = rec["session"]
        session = sessions.get(sid)
        if session is None:
            session = {"id": sid, "title": "", "updated": 0.0, "turns": 0, "preview": ""}
            sessions[sid] = session
        session["updated"] = max(session["updated"], rec["t"])
        session["turns"] += 1
        if not session["title"] and rec["user"].strip():
            session["title"] = _truncate(rec["user"], 60)
        if rec["assistant"].strip():
            session["preview"] = _truncate(rec["assistant"], 100)
    return sorted(sessions.values(), key=lambda s: s["updated"], reverse=True)


def current_session():
    global CURRENT_SESSION
    with HIST_LOCK:
        if not CURRENT_SESSION:
            CURRENT_SESSION = secrets.token_hex(6)
        return CURRENT_SESSION


def _history_snapshot():
    """Retourne (session courante, copie de HISTORY) sous HIST_LOCK."""
    with HIST_LOCK:
        return CURRENT_SESSION, [dict(m) for m in HISTORY]


def restore_history(n=6):
    global CURRENT_SESSION
    sessions = history_sessions()
    if sessions:
        sid = sessions[0]["id"]
        messages = history_messages(sid)[-20:]
        normalized = normalize([{"role": m["role"], "content": m["content"]} for m in messages])
        with HIST_LOCK:
            CURRENT_SESSION = sid
            HISTORY[:] = normalized
        return
    ev = [e for e in journal_read() if e["kind"] in ("user", "tars")][-n * 2:]
    msgs = [{"role": "user" if e["kind"] == "user" else "assistant", "content": e["text"]} for e in ev]
    with HIST_LOCK:
        HISTORY[:] = normalize(msgs)
        CURRENT_SESSION = secrets.token_hex(6)


def history_append(sid, user, assistant, replace=False):
    if not _valid_session_id(sid):
        return False
    if not str(assistant).strip():
        return False
    rec = {
        "session": sid,
        "t": time.time(),
        "user": str(user),
        "assistant": str(assistant),
    }
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with HISTORY_FILE_LOCK:
        if replace:
            records = _read_history_locked()
            for i in range(len(records) - 1, -1, -1):
                if records[i]["session"] == sid and records[i]["user"] == rec["user"]:
                    del records[i]
                    break
            records.append(rec)
            if len(records) > HISTORY_MAX_RECORDS:
                records = records[-HISTORY_MAX_RECORDS:]
            _atomic_write(HISTORY_FILE, "".join(
                json.dumps(r, ensure_ascii=False) + "\n" for r in records))
        else:
            with HISTORY_FILE.open("a", encoding="utf-8") as f:
                f.write(line)
            try:
                os.chmod(HISTORY_FILE, 0o600)
            except OSError:
                pass
            try:
                count = HISTORY_FILE.read_text("utf-8", errors="replace").count("\n")
            except OSError:
                count = 0
            if count > HISTORY_MAX_RECORDS:
                records = _read_history_locked()[-HISTORY_MAX_RECORDS:]
                _atomic_write(HISTORY_FILE, "".join(
                    json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    return True


def history_open(sid):
    global CURRENT_SESSION, TURN_GEN
    if not _valid_session_id(sid):
        return None
    current, snapshot = _history_snapshot()
    if sid == current:
        return snapshot
    records = history_records()
    if not any(rec["session"] == sid for rec in records):
        return None
    messages = _messages_from_records(records, sid)[-20:]
    normalized = normalize([{"role": m["role"], "content": m["content"]} for m in messages])
    while normalized and normalized[0]["role"] != "user":
        normalized.pop(0)
    with HIST_LOCK:
        if CURRENT_SESSION == sid:
            return [dict(m) for m in HISTORY]
        CURRENT_SESSION = sid
        HISTORY[:] = normalized
        TURN_GEN += 1
    return normalized


def history_new():
    global CURRENT_SESSION, TURN_GEN
    sid = secrets.token_hex(6)
    with HIST_LOCK:
        CURRENT_SESSION = sid
        HISTORY[:] = []
        TURN_GEN += 1
    return sid


def begin_turn(text):
    global TURN_GEN
    with HIST_LOCK:
        TURN_GEN += 1
        prev = list(HISTORY)
        if HISTORY and HISTORY[-1]["role"] == "user":
            HISTORY.pop()
        HISTORY[:] = normalize(HISTORY + [{"role": "user", "content": text}])[-20:]
        while HISTORY and HISTORY[0]["role"] != "user":
            HISTORY.pop(0)
        return TURN_GEN, prev, list(HISTORY)


def begin_regenerate():
    global TURN_GEN
    with HIST_LOCK:
        if len(HISTORY) < 2:
            return None
        if HISTORY[-2]["role"] != "user" or HISTORY[-1]["role"] != "assistant":
            return None
        TURN_GEN += 1
        prev = list(HISTORY)
        messages = [dict(m) for m in HISTORY[:-1]][-20:]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        HISTORY[:] = messages
        return TURN_GEN, prev, [dict(m) for m in messages]


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
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Tars/1.0"})
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
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Tars/1.0"})
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


def _stream_groq(system, messages, max_tokens=400):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY manquante")
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": max_tokens,
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Tars/1.0"})
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
        raise RuntimeError(f"Groq {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"Groq: {e}") from None


_STREAMS = {"groq": _stream_groq, "mistral": _stream_mistral, "anthropic": _stream_anthropic}
_DOWN = {}


def _has_key(name):
    if name == "groq":
        return bool(GROQ_API_KEY)
    return bool(MISTRAL_API_KEY) if name == "mistral" else bool(API_KEY) if name == "anthropic" else False


def stream_llm(system, messages, max_tokens=400, providers=None):
    if MOCK and not any([GROQ_API_KEY, MISTRAL_API_KEY, API_KEY]):
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


# ---------- Synthèse locale Piper ----------

def _piper_model_path():
    if not PIPER_MODEL:
        return None
    model = Path(PIPER_MODEL)
    if not model.is_absolute():
        model = ROOT / model
    return model


def _piper_bin_path():
    if not PIPER_BIN:
        return None
    found = shutil.which(PIPER_BIN)
    if found:
        return Path(found)
    candidate = Path(PIPER_BIN)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate if candidate.is_file() else None


def piper_status():
    model = _piper_model_path()
    binary = _piper_bin_path()
    available = bool(model is not None and model.is_file() and binary is not None)
    return {
        "available": available,
        "model": model.name if model is not None else "",
        "bin": binary.name if binary is not None else "",
    }


def _tts_cache_key(text, model):
    try:
        mtime = model.stat().st_mtime
    except OSError:
        mtime = 0.0
    raw = (text + "\0" + str(model) + "\0" + repr(mtime)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _tts_prune(cache):
    try:
        files = [p for p in cache.glob("*.wav") if p.is_file()]
        if len(files) <= TTS_CACHE_MAX:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        for old in files[:-TTS_CACHE_MAX]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass


# ---------- Diagnostic ----------

def _providers_snapshot():
    out, seen = [], set()
    for name in PROVIDERS:
        if name in seen or name not in _STREAMS:
            continue
        seen.add(name)
        if name == "groq":
            out.append({"name": name, "configured": bool(GROQ_API_KEY), "model": GROQ_MODEL})
        elif name == "mistral":
            out.append({"name": name, "configured": bool(MISTRAL_API_KEY), "model": MISTRAL_MODEL})
        elif name == "anthropic":
            out.append({"name": name, "configured": bool(API_KEY), "model": MODEL})
    return out


def diagnostic_snapshot():
    providers = _providers_snapshot()
    configured = [p["name"] for p in providers if p["configured"]]
    active = configured[0] if configured else ("mock" if MOCK else None)
    sessions = history_sessions()
    return {
        "server": {"ok": True},
        "auth": {"ok": bool(TOKEN)},
        "llm": {
            "ok": bool(MOCK or GROQ_API_KEY or MISTRAL_API_KEY or API_KEY),
            "active": active,
            "mock": bool(MOCK),
            "providers": providers,
        },
        "stt": {"ok": bool(GROQ_API_KEY), "model": STT_MODEL},
        "tts": {"piper": piper_status(), "fallbacks": ["web", "android"]},
        "memory": {"count": len(memory_items())},
        "history": {"sessions": len(sessions), "current": current_session()},
        "last_error": last_error_snapshot(),
    }


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "TARS"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *a):
        pass

    def _auth(self):
        if not TOKEN:
            return False
        got = self.headers.get("X-Tars-Token")
        if got is not None and hmac.compare_digest(got.encode("utf-8"), TOKEN.encode("utf-8")):
            return True
        raw = self.headers.get("Cookie", "")
        if not raw:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return False
        morsel = cookie.get("tars_session")
        if morsel is None:
            return False
        return hmac.compare_digest(morsel.value.encode("utf-8"), SESSION.encode("utf-8"))

    def _host_ok(self):
        raw = (self.headers.get("Host") or "").strip()
        if not raw:
            return False
        if raw.startswith("["):
            end = raw.find("]")
            if end < 0:
                return False
            host = raw[1:end].lower()
            rest = raw[end + 1:]
            if rest and not rest.startswith(":"):
                return False
        elif raw.count(":") == 1:
            host = raw.split(":", 1)[0].lower()
        else:
            host = raw.lower()
        allowed = {"127.0.0.1", "localhost", "::1"}
        explicit = HOST.strip().lower()
        if explicit and explicit not in ("0.0.0.0", "::"):
            allowed.add(explicit)
        return host in allowed

    def _origin_ok(self):
        raw = self.headers.get("Origin")
        if raw is None:
            return True
        try:
            parsed = urlparse(raw)
            port = parsed.port
        except ValueError:
            return False
        if parsed.scheme != "http":
            return False
        if (parsed.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
            return False
        return port == self.server.server_address[1]

    def _guard(self, check_origin=False):
        if not self._host_ok():
            self._err(403, "accès refusé")
            return False
        if check_origin and not self._origin_ok():
            self._err(403, "accès refusé")
            return False
        return True

    def _send(self, code, body, ctype="application/json; charset=utf-8", no_store=False, headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
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
            raw = self.rfile.read(n)
        except (socket.timeout, TimeoutError, OSError):
            self._err(408, "délai dépassé")
            return None
        try:
            data = json.loads(raw)
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

    def _serve_public_file(self, name, ctype, headers=None):
        """Sert un fichier public de static/ sans authentification."""
        target = (STATIC / name).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self._err(404, "introuvable")
        try:
            data = target.read_bytes()
        except OSError:
            return self._err(404, "introuvable")
        self._send(200, data, ctype, no_store=True, headers=headers)

    def _handle_config_post(self, data):
        global GROQ_API_KEY, MISTRAL_API_KEY, API_KEY, GROQ_MODEL
        updates = {}
        for key in _SECRET_FIELDS:
            if key not in data:
                continue
            val = data[key]
            if not isinstance(val, str):
                return self._err(400, f"{key} doit être une chaîne")
            updates[key] = val.strip()
        # Un modèle vide ne doit pas casser le provider : on l'ignore.
        if not updates.get("groq_model", "x"):
            updates.pop("groq_model", None)
        for key, val in updates.items():
            if key == "groq_api_key":
                GROQ_API_KEY = val
            elif key == "mistral_api_key":
                MISTRAL_API_KEY = val
            elif key == "anthropic_api_key":
                API_KEY = val
            elif key == "groq_model":
                GROQ_MODEL = val
        try:
            save_secrets(updates)
        except OSError as e:
            print(f"[CONFIG] écriture secrets.json impossible : {e}", file=sys.stderr)
            record_error("config", f"écriture secrets.json impossible : {e}")
            return self._err(500, "configuration non enregistrée")
        out = {"status": "ok"}
        out.update(config_snapshot())
        self._send(200, json.dumps(out, ensure_ascii=False))

    def _handle_design_post(self, data):
        design = data.get("design")
        if not isinstance(design, str) or design not in DESIGNS:
            return self._err(400, "design invalide")
        settings = load_settings()
        settings["design"] = design
        try:
            save_settings(settings)
        except OSError as e:
            print(f"[DESIGN] écriture settings.json impossible : {e}", file=sys.stderr)
            return self._err(500, "design non enregistré")
        self._send(200, json.dumps({"design": design}))

    def _handle_memory_post(self, data):
        action = data.get("action")
        if action == "add":
            text = _clean_fact_text(data.get("text"))
            if text is None:
                return self._err(400, "texte invalide")
            try:
                item = memory_add(text)
            except (OSError, UnicodeError) as e:
                record_error("memory", f"écriture des faits impossible : {e}")
                return self._err(500, "mémoire non enregistrée")
            if item is None:
                return self._err(400, "texte invalide")
            return self._send(200, json.dumps({"status": "ok", "fact": item}, ensure_ascii=False))
        if action == "update":
            fid = data.get("id")
            text = _clean_fact_text(data.get("text"))
            if not _valid_fact_id(fid) or text is None:
                return self._err(400, "identifiant ou texte invalide")
            try:
                item = memory_update(fid, text)
            except (OSError, UnicodeError) as e:
                record_error("memory", f"écriture des faits impossible : {e}")
                return self._err(500, "mémoire non enregistrée")
            if item is None:
                if not any(existing["id"] == fid for existing in memory_items()):
                    return self._err(404, "fait introuvable")
                return self._err(400, "doublon")
            return self._send(200, json.dumps({"status": "ok", "fact": item}, ensure_ascii=False))
        if action == "delete":
            fid = data.get("id")
            if not _valid_fact_id(fid):
                return self._err(400, "identifiant invalide")
            try:
                deleted = memory_delete(fid)
            except (OSError, UnicodeError) as e:
                record_error("memory", f"écriture des faits impossible : {e}")
                return self._err(500, "mémoire non enregistrée")
            if not deleted:
                return self._err(404, "fait introuvable")
            return self._send(200, json.dumps({"status": "ok"}))
        if action == "clear":
            try:
                memory_clear()
            except (OSError, UnicodeError) as e:
                record_error("memory", f"écriture des faits impossible : {e}")
                return self._err(500, "mémoire non enregistrée")
            return self._send(200, json.dumps({"status": "ok"}))
        return self._err(400, "action invalide")

    def _handle_propose_post(self, data):
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return self._err(400, "texte invalide")
        try:
            candidates = extract_memory_proposals(text[:MAX_TEXT])
            items, created = proposals_create(candidates)
        except (OSError, UnicodeError) as e:
            record_error("memory", f"écriture des propositions impossible : {e}")
            return self._err(500, "mémoire non enregistrée")
        self._send(200, json.dumps({"items": items, "created": created}, ensure_ascii=False))

    def _handle_proposals_post(self, data):
        action = data.get("action")
        pid = data.get("id")
        if action not in ("accept", "reject") or not _valid_proposal_id(pid):
            return self._err(400, "action ou identifiant invalide")
        try:
            result = proposals_decide(action, pid)
        except (OSError, UnicodeError) as e:
            record_error("memory", f"écriture des propositions impossible : {e}")
            return self._err(500, "mémoire non enregistrée")
        if result is None:
            return self._err(404, "proposition introuvable")
        if result["invalid"]:
            return self._err(400, "texte invalide")
        payload = {"status": "ok", "action": action, "items": result["items"]}
        if action == "accept":
            payload["fact"] = result["fact"]
        self._send(200, json.dumps(payload, ensure_ascii=False))

    def _handle_tts(self, data):
        text = data.get("text")
        if not isinstance(text, str):
            return self._err(400, "texte invalide")
        text = text.strip()
        if not text:
            return self._err(400, "texte vide")
        if len(text) > MAX_TTS:
            return self._err(400, "texte trop long")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            return self._err(400, "texte invalide")
        if not piper_status()["available"]:
            return self._err(503, "voix locale indisponible")
        model = _piper_model_path()
        binary = _piper_bin_path()
        key = _tts_cache_key(text, model)
        cache = TTS_CACHE
        try:
            cache.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(cache, 0o700)
            except OSError:
                pass
        except OSError as e:
            record_error("tts", f"dossier de cache indisponible : {e}")
            return self._err(502, "synthèse locale indisponible")

        with TTS_LOCK:
            out = cache / (key + ".wav")
            try:
                if out.is_file():
                    return self._send(200, out.read_bytes(), "audio/wav", no_store=True)
            except OSError:
                pass
            tmp = cache / (key + ".part.wav")
            try:
                tmp.unlink()
            except OSError:
                pass
            try:
                proc = subprocess.run(
                    [str(binary), "--model", str(model), "--output_file", str(tmp)],
                    input=text.encode("utf-8"),
                    timeout=30,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except subprocess.TimeoutExpired:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                record_error("tts", "délai de synthèse dépassé")
                return self._err(502, "synthèse locale indisponible")
            except OSError as e:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                record_error("tts", f"exécution piper impossible : {e}")
                return self._err(502, "synthèse locale indisponible")
            if proc.returncode != 0 or not tmp.is_file():
                detail = (proc.stderr or b"")[:200].decode("utf-8", "replace").strip()
                try:
                    tmp.unlink()
                except OSError:
                    pass
                record_error("tts", detail or f"piper code {proc.returncode}")
                return self._err(502, "synthèse locale indisponible")
            try:
                os.chmod(tmp, 0o600)
                os.replace(tmp, out)
                wav = out.read_bytes()
            except OSError as e:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                record_error("tts", f"écriture du cache impossible : {e}")
                return self._err(502, "synthèse locale indisponible")
            _tts_prune(cache)
            return self._send(200, wav, "audio/wav", no_store=True)

    def _handle_stt(self):
        if not GROQ_API_KEY:
            record_error("stt", "clé Groq absente")
            return self._err(503, "clé Groq requise pour la transcription")
        raw_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = _AUDIO_TYPES.get(raw_type)
        if not ext:
            return self._err(415, "format audio non supporté")
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = -1
        if n <= 0:
            return self._err(400, "audio attendu")
        if n > MAX_AUDIO:
            return self._err(413, "audio trop gros (10 Mo max)")
        try:
            audio = self.rfile.read(n)
        except (socket.timeout, TimeoutError, OSError):
            return self._err(408, "délai dépassé")
        if len(audio) != n:
            return self._err(400, "audio incomplet")

        boundary = "----TarsBoundary" + os.urandom(12).hex()
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="audio.{ext}"\r\n'
            f"Content-Type: {raw_type}\r\n\r\n"
        ).encode("ascii")
        tail = (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{STT_MODEL}"
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nfr"
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\njson"
            f"\r\n--{boundary}--\r\n"
        ).encode("ascii")
        req = urllib.request.Request(
            STT_URL, data=head + audio + tail, method="POST",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": f"multipart/form-data; boundary={boundary}",
                     "User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            print(f"[STT] Groq {e.code}: {msg}", file=sys.stderr)
            record_error("stt", f"Groq {e.code}: {msg}")
            return self._err(502, "transcription indisponible")
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"[STT] Groq: {e}", file=sys.stderr)
            record_error("stt", f"Groq: {e}")
            return self._err(502, "transcription indisponible")
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            print("[STT] réponse Groq invalide", file=sys.stderr)
            record_error("stt", "réponse Groq invalide")
            return self._err(502, "transcription indisponible")
        self._send(200, json.dumps({"text": text}, ensure_ascii=False))

    def do_OPTIONS(self):
        if not self._guard():
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._guard():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/manifest.webmanifest":
            return self._serve_public_file("manifest.webmanifest", "application/manifest+json")
        if path == "/sw.js":
            return self._serve_public_file(
                "sw.js", "application/javascript; charset=utf-8",
                headers={"Service-Worker-Allowed": "/"})
        if path == "/":
            query = parse_qs(parsed.query, keep_blank_values=True)
            if "boot" in query:
                global BOOT_NONCE
                boot = (query.get("boot") or [""])[0]
                if BOOT_NONCE and boot and hmac.compare_digest(boot, BOOT_NONCE):
                    BOOT_NONCE = ""
                    self._send(
                        302, b"", "text/plain; charset=utf-8", no_store=True,
                        headers={
                            "Location": "/",
                            "Set-Cookie": f"tars_session={SESSION}; HttpOnly; SameSite=Strict; Path=/",
                        })
                    return
                return self._err(403, "bootstrap invalide")
            try:
                html = (ROOT / "index.html").read_text("utf-8")
            except (OSError, UnicodeDecodeError):
                return self._err(404, "index.html introuvable")
            body = inject_design(html, load_settings()["design"])
            self._send(200, body, "text/html; charset=utf-8", no_store=True)
        elif path == "/health":
            self._send(200, json.dumps({"ok": True}), no_store=True)
        elif path == "/state":
            if not self._auth():
                return self._err(401, "token")
            self._send(200, json.dumps(load_settings()), no_store=True)
        elif path == "/config":
            if not self._auth():
                return self._err(401, "token")
            self._send(200, json.dumps(config_snapshot()), no_store=True)
        elif path == "/diagnostic":
            if not self._origin_ok():
                return self._err(403, "accès refusé")
            if not self._auth():
                return self._err(401, "token")
            self._send(200, json.dumps(diagnostic_snapshot(), ensure_ascii=False), no_store=True)
        elif path == "/memory":
            if not self._origin_ok():
                return self._err(403, "accès refusé")
            if not self._auth():
                return self._err(401, "token")
            items = memory_items()
            self._send(200, json.dumps({"facts": items, "count": len(items)}, ensure_ascii=False),
                       no_store=True)
        elif path == "/memory/proposals":
            if not self._origin_ok():
                return self._err(403, "accès refusé")
            if not self._auth():
                return self._err(401, "token")
            items = pending_proposals()
            self._send(200, json.dumps({"items": items, "count": len(items)}, ensure_ascii=False),
                       no_store=True)
        elif path == "/memory/export":
            if not self._origin_ok():
                return self._err(403, "accès refusé")
            if not self._auth():
                return self._err(401, "token")
            self._send(
                200, memory_export(), "text/markdown; charset=utf-8", no_store=True,
                headers={"Content-Disposition": 'attachment; filename="tars-memoire.md"'})
        elif path == "/history":
            if not self._origin_ok():
                return self._err(403, "accès refusé")
            if not self._auth():
                return self._err(401, "token")
            self._send(200, json.dumps({"current": current_session(), "sessions": history_sessions()},
                                       ensure_ascii=False), no_store=True)
        elif path.startswith("/history/"):
            if not self._origin_ok():
                return self._err(403, "accès refusé")
            if not self._auth():
                return self._err(401, "token")
            sid = path[len("/history/"):]
            if not _valid_session_id(sid):
                return self._err(404, "introuvable")
            current, snapshot = _history_snapshot()
            if sid == current:
                self._send(200, json.dumps({"id": sid, "messages": snapshot[-20:]},
                                           ensure_ascii=False), no_store=True)
                return
            records = history_records()
            if not any(rec["session"] == sid for rec in records):
                return self._err(404, "introuvable")
            messages = _messages_from_records(records, sid)[-20:]
            self._send(200, json.dumps({"id": sid, "messages": messages},
                                       ensure_ascii=False), no_store=True)
        elif path == "/widget":
            # Endpoint public pour les widgets (statut et réglages uniquement)
            self._send(200, json.dumps(widget_state()), no_store=True)
        elif path.startswith("/static/"):
            self._serve_static(path)
        else:
            self._err(404, "introuvable")

    def do_POST(self):
        if not self._guard(check_origin=True):
            return
        path = urlparse(self.path).path
        allowed = ("/chat", "/status", "/config", "/stt", "/design", "/tts", "/memory",
                   "/memory/propose", "/memory/proposals",
                   "/history/open", "/history/new")
        if path not in allowed:
            return self._err(404, "introuvable")
        if not self._auth():
            return self._err(401, "token")
        if path == "/stt":
            return self._handle_stt()
        if path == "/history/new":
            return self._send(200, json.dumps({"id": history_new()}))
        data = self._read_json()
        if data is None:
            return

        if path == "/config":
            return self._handle_config_post(data)

        if path == "/design":
            return self._handle_design_post(data)

        if path == "/memory":
            return self._handle_memory_post(data)

        if path == "/memory/propose":
            return self._handle_propose_post(data)

        if path == "/memory/proposals":
            return self._handle_proposals_post(data)

        if path == "/tts":
            return self._handle_tts(data)

        if path == "/history/open":
            sid = data.get("id")
            if not _valid_session_id(sid):
                return self._err(400, "identifiant invalide")
            messages = history_open(sid)
            if messages is None:
                return self._err(404, "session introuvable")
            self._send(200, json.dumps({"id": sid, "messages": messages}, ensure_ascii=False))
            return

        if path == "/status":
            st = data.get("status")
            if st not in STATUSES:
                return self._err(400, "état invalide")
            set_status(st, from_client=True)
            self._send(200, json.dumps({"status": "ok"}))
            return

        # Gestion de /chat
        sid = current_session()
        regenerate = data.get("regenerate") is True
        if regenerate:
            wanted = data.get("session")
            if wanted is not None:
                if not _valid_session_id(wanted) or wanted != sid:
                    return self._err(409, "session obsolète")
            started = begin_regenerate()
            if started is None:
                return self._err(409, "rien à régénérer")
            gen, prev, messages = started
            text = messages[-1]["content"] if messages and messages[-1]["role"] == "user" else ""
            if not text:
                rollback(gen, prev)
                return self._err(409, "rien à régénérer")
            if current_session() != sid:
                rollback(gen, prev)
                return self._err(409, "session obsolète")
            expected_user = data.get("user")
            if expected_user is not None:
                if not isinstance(expected_user, str) or text.strip() != expected_user.strip():
                    rollback(gen, prev)
                    return self._err(409, "rien à régénérer")
            set_status("thinking")
        else:
            text = data.get("text")
            if not isinstance(text, str):
                return self._err(400, "texte invalide")
            text = text.strip()
            if not text:
                return self._err(400, "texte vide")
            if len(text) > MAX_TEXT:
                text = text[:MAX_TEXT]
            set_status("thinking")
            gen, prev, messages = begin_turn(text)

        # Initialiser la réponse HTTP pour le streaming SSE
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        reply, buf, first = "", "", True
        try:
            settings = load_settings()
            if regenerate:
                changes = {}
            else:
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
            print(f"[CHAT] fournisseur indisponible : {e}", file=sys.stderr)
            record_error("chat", str(e))
            try:
                self._emit({"error": "provider", "s": "Liaison coupée, commandant. Je ne peux pas joindre le cerveau."})
            except ConnectionError:
                pass  # Client déjà déconnecté
            set_status("off")
            return
        except Exception as e:
            rollback(gen, prev)
            print(f"[CHAT] erreur interne : {e!r}", file=sys.stderr)
            record_error("chat", repr(e))
            try:
                self._emit({"error": "internal", "s": "Erreur critique, commandant."})
            except ConnectionError:
                pass  # Client déjà déconnecté
            set_status("off")
            return

        if not finish_turn(gen, reply):
            return  # un tour plus récent a pris la main

        try:
            history_append(sid, text, reply.strip(), replace=regenerate)
        except (OSError, UnicodeError) as e:
            print(f"[HISTORY] écriture history.jsonl impossible : {e}", file=sys.stderr)
            record_error("history", f"écriture history.jsonl impossible : {e}")

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


class TarsServer(ThreadingHTTPServer):
    daemon_threads = True


# ---------- Consolidation nocturne ----------

def consolidate():
    since = read_mark()
    meta = _load_facts_meta()
    tombstones = set(meta["tombstones"])
    epoch = meta["cleared_at"]
    ev = []
    for e in journal_read():
        if e["t"] <= since or e["t"] <= epoch:
            continue
        if e["kind"] != "fact":
            continue
        key = _tombstone_key(e["text"])
        if key is None or key in tombstones:
            continue
        ev.append(e)
    if not ev:
        print("Rien de nouveau dans le journal.")
        return
    try:
        old = FACTS.read_text("utf-8")
    except OSError:
        old = ""
    old_lines = []
    for line in old.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            key = _tombstone_key(stripped[2:])
            if key is None or key in tombstones:
                continue
        old_lines.append(line)
    old = "\n".join(old_lines)
    
    # Préparer le log des nouveaux faits
    log = "\n".join(f"[{e['kind']}] {e['text']}" for e in ev)
    ev_facts = [e for e in ev if e["kind"] == "fact"]
    new_facts = "\n".join(f"- {e['text']}" for e in ev_facts)
    old_bullets = "\n".join(
        line.strip() for line in old.splitlines() if line.strip().startswith("- "))
    
    # Si on a Groq, Mistral ou Anthropic, utiliser l'API pour consolider
    if GROQ_API_KEY:
        try:
            prompt = ("Voici la liste actuelle des faits sur le commandant, puis le journal récent.\n"
                     "Réécris la liste complète : un fait court par ligne commençant par '- ', uniquement des faits "
                     "durables et explicitement dits par le commandant, sans doublon, sans rien inventer. "
                     "Les lignes [fact] sont à retenir en priorité. Réponds uniquement par la liste.\n\n"
                     f"FAITS ACTUELS:\n{old}\n\nJOURNAL:\n{log}")
            out = "".join(_stream_groq("Tu es un archiviste rigoureux.", [{"role": "user", "content": prompt}], CONSOLIDATE_CHUNK)).strip()
        except Exception as e:
            print(f"[CONSOLIDATE] Groq échoué: {e}. Passage en mode manuel.")
            out = old_bullets + ("\n" + new_facts if old_bullets else new_facts)
    elif MISTRAL_API_KEY:
        try:
            prompt = ("Voici la liste actuelle des faits sur le commandant, puis le journal récent.\n"
                     "Réécris la liste complète : un fait court par ligne commençant par '- ', uniquement des faits "
                     "durables et explicitement dits par le commandant, sans doublon, sans rien inventer. "
                     "Les lignes [fact] sont à retenir en priorité. Réponds uniquement par la liste.\n\n"
                     f"FAITS ACTUELS:\n{old}\n\nJOURNAL:\n{log}")
            out = "".join(_stream_mistral("Tu es un archiviste rigoureux.", [{"role": "user", "content": prompt}], CONSOLIDATE_CHUNK)).strip()
        except Exception as e:
            print(f"[CONSOLIDATE] Mistral échoué: {e}. Passage en mode manuel.")
            out = old_bullets + ("\n" + new_facts if old_bullets else new_facts)
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
            out = old_bullets + ("\n" + new_facts if old_bullets else new_facts)
    else:
        # Mode manuel : ajouter les nouveaux faits à l'ancien, sans doublon
        if not ev_facts:
            print("Rien de nouveau à consolider en mode manuel.")
            return
        lignes, vus = [], set()
        for ligne in old.splitlines():
            stripped = ligne.strip()
            if not stripped.startswith("- "):
                continue
            cle = stripped.lower()
            if cle not in vus:
                vus.add(cle)
                lignes.append(stripped)
        for e in ev_facts:
            ligne = f"- {e['text']}"
            cle = ligne.strip().lower()
            if cle not in vus:
                vus.add(cle)
                lignes.append(ligne)
        out = "\n".join(lignes)
    
    lines, seen = [], set()
    for raw in out.splitlines():
        stripped = raw.strip()
        if not stripped.startswith("- "):
            continue
        text = _clean_fact_text(stripped[2:].strip()[:MAX_FACT])
        if text is None:
            continue
        key = text.lower()
        if key in tombstones or key in seen:
            continue
        seen.add(key)
        lines.append("- " + text)
    if not lines:
        print("Réponse inattendue du modèle, facts.md non modifié.")
        return
    out = "\n".join(lines)
    
    # Sauvegarde de sécurité
    if FACTS.exists():
        shutil.copy2(FACTS, FACTS_BAK)
    
    if sync_memory_from_lines(out.splitlines(), expected_cleared_at=epoch) is None:
        print("Mémoire effacée pendant la consolidation, écriture abandonnée.")
        return
    MARK.write_text(str(max(e["t"] for e in ev)), encoding="utf-8")
    print(f"{len(ev)} événements consolidés -> {FACTS}")


if __name__ == "__main__":
    load_secrets()

    if len(sys.argv) > 1 and sys.argv[1] == "consolidate":
        consolidate()
        sys.exit(0)
    
    if not MOCK and not any([GROQ_API_KEY, MISTRAL_API_KEY, API_KEY]):
        print("Définis GROQ_API_KEY (recommandé), MISTRAL_API_KEY ou ANTHROPIC_API_KEY (ou TARS_MOCK=1 pour tester sans clé).")
        print("Exemple : GROQ_API_KEY=ta_clé python3 Tars.py")
        sys.exit(1)

    load_fact_events()
    restore_history()
    httpd = TarsServer((HOST, PORT), Handler)
    real_port = httpd.server_address[1]
    print(f"TARS_READY port={real_port}", flush=True)
    print(f"TARS en ligne -> http://localhost:{real_port}/?boot={get_boot_nonce()}", flush=True)
    httpd.serve_forever()
