# Tars pas tars

**Assistant vocal personnel avec personnalité TARS (Interstellar) - Version 100% locale**

---

## 🎯 Objectif

Créer un assistant vocal **ultra-rapide** (< 1s de latence) avec la personnalité de TARS, **100% fonctionnel en local** (sans dépendance à un Raspberry Pi ou à des APIs externes, sauf optionnellement pour le LLM).

**Nouveautés** :
- ✅ **100% local** : Plus besoin de Raspberry Pi, tout tourne sur l'appareil
- ✅ **Applications natives** : Android (Java natif + Chaquopy/WebView) et Windows (Electron)
- ✅ **Widgets** : Widget Android natif + Widget Windows (Rainmeter)
- ✅ **Fallback intégré** : Si le backend est down, bascule en mode local
- ✅ **Clips audio** : Accusés de réception préenregistrés (optionnels)

---

## 📁 Structure du Projet

```
Tars/
├── Tars.py                  # Backend Python (serveur HTTP + LLM)
├── index.html               # Frontend web (interface utilisateur)
├── generate_acks.py         # Script pour générer les clips audio
├── data/                    # Données locales (mémoire, réglages)
│   ├── journal.jsonl        # Journal des événements
│   ├── facts.md             # Faits consolidés
│   ├── settings.json        # Réglages (humour, honnêteté)
│   └── consolidated_until.txt
├── static/                  # Fichiers statiques
│   └── acks/                # Clips audio pour accusés de réception
│       ├── court/           # Accusés courts (Reçu, Mmh, etc.)
│       ├── reflexion/       # Accusés de réflexion
│       └── drole/           # Accusés drôles
├── android/                 # Application Android native (Java + Chaquopy/WebView)
│   ├── app/                 # Code natif Android et Python embarqué
│   └── README.md
└── windows/                 # Application Windows
    ├── main.js             # Point d'entrée Electron
    ├── preload.js          # Pré-chargement
    ├── TarsWidget.ini      # Widget Rainmeter
    ├── TarsWidget.lua      # Script Lua pour le widget
    └── README.md
```

`data/` et `data/secrets.json` ne doivent jamais être commités. Le backend applique des permissions `700` sur `data/` et `600` sur les fichiers sensibles, en best-effort selon la plateforme.

---

## 🚀 Installation et Utilisation

### 1. Prérequis Communs
- **Python 3.8+** (pour le backend)
- **Node.js 18+** (pour l'application Windows/Electron)
- **Android Studio** (pour builder l'APK Android)

### 2. Backend (Tars.py)

#### Installation
```bash
# Cloner le dépôt
cd Tars

# Aucune dépendance pour le backend (stdlib uniquement)
# Pour générer des clips audio (optionnel) :
pip install gtts pydub  # Pour gTTS
# OU
pip install piper-tts    # Pour Piper (local)
```

#### Démarrer le backend
```bash
# Avec votre clé Groq (recommandé)
GROQ_API_KEY=votre_clé_ici python3 Tars.py

# Avec votre clé Mistral
MISTRAL_API_KEY=votre_clé_ici python3 Tars.py

# Avec votre clé Anthropic
ANTHROPIC_API_KEY=votre_clé_ici python3 Tars.py

# Mode mock (100% local, sans API, réponses basiques)
TARS_MOCK=1 python3 Tars.py

# Consolider le journal (pour sauvegarder les faits)
python3 Tars.py consolidate
```

#### Configuration rapide
```bash
# Créer un alias pour lancer facilement (Termux/Linux/Mac)
echo "alias tars='MISTRAL_API_KEY=mstrl_votre_clé_ici python3 ~/Tars/Tars.py'" >> ~/.bashrc
source ~/.bashrc

# Puis simplement :
tars
```

Le serveur affiche son port au démarrage (`TARS_READY port=<port>`). En lancement manuel, le port par défaut est `8000` : ouvrir une seule fois l'URL de bootstrap affichée dans la console, `http://localhost:8000/?boot=<nonce>`.

Si `TARS_TOKEN` n'est pas défini, un token est généré automatiquement. Il n'est pas affiché : pour authentifier des scripts, définir explicitement `TARS_TOKEN` et envoyer l'en-tête `X-Tars-Token`.

#### Générer les clips audio
```bash
# Générer des clips dummy (pour test)
python3 generate_acks.py --method dummy

# Générer avec gTTS (nécessite internet)
python3 generate_acks.py --method gtts

# Générer avec Piper (nécessite un modèle local)
python3 generate_acks.py --method piper
```

### 3. Application Android

Voir : [android/README.md](android/README.md)

### 4. Application Windows

Voir : [windows/README.md](windows/README.md)

---

## 📱 Applications Natives

### Android
- **Technologie** : Java natif + Chaquopy (Python embarqué) + WebView, sans Capacitor
- **Backend** : intégré à l'APK via Chaquopy ; port aléatoire (`TARS_PORT=0`)
- **Démarrage** : l'application attend que `/health` réponde avant d'ouvrir la WebView
- **Widget** : widget natif Android
- **Sécurité** : `allowBackup="false"`, trafic clair limité à la boucle locale (`127.0.0.1`, `localhost`), `data/` non versionné
- **Installation** : builder l'APK avec Android Studio/Gradle

### Windows
- **Technologie** : Electron
- **Backend** : `Tars.exe` (généré avec PyInstaller)
- **Port** : port libre choisi au démarrage
- **Sécurité** : token et nonce passés par `TARS_TOKEN`/`TARS_BOOT_NONCE`, données dans `app.getPath('userData')/data` via `TARS_DATA`
- **Build** : `npm run build-exe` (PyInstaller avec `--add-data "../index.html;." --add-data "../static;static"`)
- **Widget** : Rainmeter (optionnel)
- **Installation** : builder l'installateur avec `npm run dist`

---

## 🎛️ Fonctionnalités

### Backend (Tars.py)
- **Serveur HTTP** : Gère les requêtes du frontend
- **LLM** : Streaming avec Mistral/Anthropic (ou mode mock 100% local)
- **Mémoire** : Journal append-only + consolidation nocturne
- **Réglages** : Humour et honnêteté persistants
- **Endpoint `/widget`** : Pour les widgets (Android/Windows)
- **Fallback** : Si les APIs échouent, bascule en mode mock
- **Sécurité** : authentification fail-closed (cookie de session ou `X-Tars-Token`), `/health` public, contrôle du `Host` (loopback) et de l'`Origin` sur les POST, protection contre le path traversal, CORS supprimé
- **Bootstrap** : `/?boot=<nonce>` répond `302`, pose un cookie `HttpOnly; SameSite=Strict` et consomme le nonce
- **Token** : auto-généré si `TARS_TOKEN` est absent ; jamais dans l'URL ni dans `localStorage`

### Frontend (index.html)
- **Interface minimaliste** : Bouton monolithe, affichage des messages
- **Reconnaissance vocale** : Web Speech API (Chrome/Edge)
- **Synthèse vocale** : Web Speech API (voix robotique)
- **Streaming** : Réception des réponses en temps réel
- **Barge-in** : Interruption si l'utilisateur parle pendant la réponse
- **Accusés de réception** : Clips audio ou synthèse vocale
- **Mode widget** : Affichage minimal pour les widgets

### Widgets
- **Android** : Widget natif avec état et bouton de contrôle
- **Windows** : Widget Rainmeter avec état et bouton

---

## 🔧 Configuration

### Variables d'Environnement
| Variable | Description | Défaut | Obligatoire |
|----------|-------------|--------|--------------|
| `TARS_DATA` | Dossier des données | `./data` | Non |
| `ANTHROPIC_API_KEY` | Clé API Anthropic | - | Non (mode mock disponible) |
| `TARS_MODEL` | Modèle Anthropic | `claude-haiku-4-5-20251001` | Non |
| `GROQ_API_KEY` | Clé API Groq | - | Non |
| `GROQ_MODEL` | Modèle Groq | `openai/gpt-oss-120b` | Non |
| `TARS_TOKEN` | Token API ; auto-généré s'il est absent, non affiché | auto | Non |
| `TARS_BOOT_NONCE` | Nonce de bootstrap à usage unique (`/?boot=...`) | auto | Non |
| `TARS_HOST` | Hôte du serveur | `127.0.0.1` | Non |
| `TARS_PORT` | Port d'écoute ; `8000` en manuel, `0` = port aléatoire (Android/Electron) | `8000` | Non |
| `TARS_MOCK` | Mode mock | `0` | Non |

### Exemple
```bash
# Démarrer avec un modèle spécifique et en mode mock
TARS_MODEL=claude-3-sonnet-20240229 TARS_MOCK=1 python3 Tars.py

# Démarrer avec une clé API Anthropic
ANTHROPIC_API_KEY=sk-... python3 Tars.py
```

### Sécurité et authentification

- Si `TARS_TOKEN` est absent, un token est généré automatiquement et n'est pas affiché.
- L'authentification est fail-closed : `/health` reste public, les endpoints sensibles exigent un cookie de session ou l'en-tête `X-Tars-Token` (scripts avec `TARS_TOKEN` explicite).
- Bootstrap : ouvrir `http://localhost:<port>/?boot=<nonce>` une seule fois. Le serveur répond `302` et pose un cookie `HttpOnly; SameSite=Strict` ; le nonce est consommé.
- Le token n'est jamais placé dans l'URL ni dans `localStorage`.
- Le serveur vérifie le `Host` (loopback : `127.0.0.1`, `localhost`, `::1`) et, pour les POST, l'`Origin` local avec le bon port.
- Aucun en-tête CORS n'est émis.

---

## 💬 Commandes Vocales

### Réglages
- "TARS, humour à 60 %" → Règle l'humour à 60%
- "TARS, honnêteté à 90 %" → Règle l'honnêteté à 90%

### Mémoire
- "TARS, retiens que j'aime le café" → Ajoute un fait
- "TARS, souviens-toi que la mission est importante" → Ajoute un fait

### Contrôle
- "fin de mission" → Quitte le personnage TARS

---

## 🎨 Personnalisation

### Voix
- **Web Speech API** : Utilise la voix française par défaut
- **Clips audio** : Pour les accusés de réception (optionnel)
- **Paramètres** : `pitch: 0.7`, `rate: 1.08` pour un effet robotique

### Personnage
- **Humour** : 0-100% (0 = factuel, 100 = ironique)
- **Honnêteté** : 0-100% (0 = tactique, 100 = franc)

### Accusés de Réception
- **Court** : "Reçu.", "Mmh.", "Compris."
- **Réflexion** : "Hm. Voyons.", "Une seconde."
- **Drôle** : "Reçu. Je fais semblant d'être surpris."

---

## 📊 Pipeline Technique

```
Vocal (utilisateur)
    ↓ [Web Speech API - STT]
Texte
    ↓ [POST /chat]
Backend (Tars.py)
    ↓ [LLM Streaming]
Réponse texte
    ↓ [Streaming SSE]
Frontend
    ↓ [Web Speech API - TTS]
Vocal (TARS)
```

---

## 🔌 Intégration avec des APIs Cloud (Optionnel)

### STT (Speech-to-Text)
- **Web Speech API** (intégré, côté client)
- **AssemblyAI** (recommandé pour le serveur)
- **Whisper** (local, via `whisper.cpp`)

### LLM (Large Language Model)
- **Anthropic Claude** (intégré, streaming)
- **Llama.cpp** (local)
- **Mistral** (local)

### TTS (Text-to-Speech)
- **Web Speech API** (intégré, côté client)
- **ElevenLabs** (recommandé pour le serveur)
- **Piper** (local)

---

## 🐛 Dépannage

### Le backend ne démarre pas
- Vérifiez que Python 3.8+ est installé
- Exécutez `python3 Tars.py` manuellement pour voir les erreurs
- Le port réel est affiché au démarrage : `TARS_READY port=<port>`
- En lancement manuel, gardez `TARS_PORT=8000` (ou `0` pour un port aléatoire) et vérifiez que ce port est libre

### Le frontend ne se connecte pas
- Vérifiez que le backend est en cours d'exécution et que `/health` répond
- Ouvrez l'URL de bootstrap affichée dans la console : `http://localhost:<port>/?boot=<nonce>` (une seule fois)
- En manuel, l'URL par défaut est `http://localhost:8000/?boot=<nonce>` ; Android et Electron choisissent un port aléatoire
- Vérifiez la console du navigateur (F12)

### La reconnaissance vocale ne fonctionne pas
- Utilisez **Chrome** ou **Edge** (Web Speech API nécessaire)
- Autorisez l'accès au micro dans les paramètres du navigateur
- Vérifiez que le micro fonctionne (testez avec un autre site)

### Les clips audio ne se jouent pas
- Vérifiez que les fichiers existent dans `static/acks/`
- Vérifiez que le serveur les sert correctement (`http://localhost:<port>/static/acks/court/recu.mp3`)
- Essayez de générer les clips avec `generate_acks.py`

---

## 📚 Documentation Complète

- [Android](android/README.md)
- [Windows](windows/README.md)
- [Backend](Tars.py) (commentaires dans le code)
- [Frontend](index.html) (commentaires dans le code)

---

## 🤝 Contribution

1. Fork le projet
2. Créez une branche (`git checkout -b feature/ma-fonctionnalité`)
3. Commitez vos changements (`git commit -m 'Ajout de ma fonctionnalité'`)
4. Poussez vers la branche (`git push origin feature/ma-fonctionnalité`)
5. Ouvrez une Pull Request

---

## 📜 Licence

MIT
