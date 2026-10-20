"""Point d'entree TARS embarque (Chaquopy).

Prepare l'environnement AVANT d'importer Tars (qui lit os.environ
au moment de l'import : DATA, HOST, PORT, MOCK...).
"""

import errno
import os


def _setup_env():
    from java import jclass

    app = jclass("android.app.ActivityThread").currentApplication()
    data_dir = os.path.join(app.getFilesDir().getAbsolutePath(), "tars_data")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["TARS_DATA"] = data_dir
    os.environ.setdefault("TARS_HOST", "127.0.0.1")
    os.environ.setdefault("TARS_PORT", "8000")
    if not any(
        os.environ.get(k)
        for k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY")
    ):
        os.environ["TARS_MOCK"] = "1"


_setup_env()

import Tars  # noqa: E402  (apres la config env)

Tars.load_fact_events()
Tars.restore_history()


def run():
    try:
        Tars.ThreadingHTTPServer((Tars.HOST, Tars.PORT), Tars.Handler).serve_forever()
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            return
        print("Erreur serveur TARS: %s" % exc)
    except Exception as exc:
        print("Erreur serveur TARS: %s" % exc)
