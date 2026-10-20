"""Point d'entree TARS embarque (Chaquopy).

Prepare l'environnement AVANT d'importer Tars (qui lit os.environ
au moment de l'import : DATA, HOST, PORT, MOCK...).
"""

import os
import threading


def _setup_env():
    from java import jclass

    app = jclass("android.app.ActivityThread").currentApplication()
    data_dir = os.path.join(app.getFilesDir().getAbsolutePath(), "tars_data")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["TARS_DATA"] = data_dir
    os.environ.setdefault("TARS_HOST", "127.0.0.1")
    os.environ["TARS_PORT"] = "0"
    if not any(
        os.environ.get(k)
        for k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY")
    ):
        os.environ["TARS_MOCK"] = "1"


_setup_env()

import Tars  # noqa: E402  (apres la config env)

Tars.load_fact_events()
Tars.restore_history()

_server = None
_port = 0
_lock = threading.Lock()


def start():
    global _server, _port
    with _lock:
        if _server is not None:
            return _port
        _server = Tars.TarsServer((Tars.HOST, Tars.PORT), Tars.Handler)
        _port = _server.server_address[1]
        threading.Thread(target=_server.serve_forever, daemon=True).start()
        return _port


def get_port():
    return _port


def get_boot_nonce():
    return Tars.get_boot_nonce()
