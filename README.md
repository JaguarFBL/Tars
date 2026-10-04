# Tars pas tars

**Assistant vocal personnel avec personnalité TARS (Interstellar) - Version 100% locale**

---

## 🎯 Objectif

Créer un assistant vocal **ultra-rapide** (< 1s de latence) avec la personnalité de TARS, **100% fonctionnel en local** (sans dépendance à un Raspberry Pi ou à des APIs externes, sauf optionnellement pour le LLM).

**Nouveautés** :
- ✅ **100% local** : Plus besoin de Raspberry Pi, tout tourne sur l'appareil
- ✅ **Applications natives** : Android (via Capacitor) et Windows (via Electron)
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
├── android/                 # Application Android
│   ├── www/                # Frontend pour Android
│   ├── app/                # Code natif Android
│   ├── capacitor.config.json
│   └── README.md
└── windows/                 # Application Windows
    ├── main.js             # Point d'entrée Electron
    ├── preload.js          # Pré-chargement
    ├── TarsWidget.ini      # Widget Rainmeter
    ├── TarsWidget.lua      # Script Lua pour le widget
    └── README.md
```

---

## 🚀 Installation et Utilisation

### 1. Prérequis Communs
- **Python 3.8+** (pour le backend)
- **Node.js 18+** (pour les applications Android/Windows)

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
# Avec votre clé Mistral (recommandé)
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

Le backend sera accessible à : **http://localhost:8000**

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
- **Technologie** : Capacitor + WebView
- **Backend** : Exécuté via Termux (ou Chaquopy pour une intégration complète)
- **Widget** : Widget natif Android
- **Installation** : Builder l'APK avec Android Studio

### Windows
- **Technologie** : Electron
- **Backend** : `Tars.exe` (généré avec PyInstaller)
- **Widget** : Rainmeter (optionnel)
- **Installation** : Builder l'installateur avec `npm run dist`

---

## 🎛️ Fonctionnalités

### Backend (Tars.py)
- **Serveur HTTP** : Gère les requêtes du frontend
- **LLM** : Streaming avec Mistral/Anthropic (ou mode mock 100% local)
- **Mémoire** : Journal append-only + consolidation nocturne
- **Réglages** : Humour et honnêteté persistants
- **Endpoint `/widget`** : Pour les widgets (Android/Windows)
- **Fallback** : Si les APIs échouent, bascule en mode mock
- **Sécurité** : Protection contre path traversal, token obligatoire pour les endpoints sensibles

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
| `TARS_TOKEN` | Token de sécurité | - | Non (uniquement si `HOST != 127.0.0.1`) |
| `TARS_HOST` | Hôte du serveur | `127.0.0.1` | Non |
| `TARS_PORT` | Port du serveur | `8000` | Non |
| `TARS_MOCK` | Mode mock | `0` | Non |

### Exemple
```bash
# Démarrer avec un modèle spécifique et en mode mock
TARS_MODEL=claude-3-sonnet-20240229 TARS_MOCK=1 python3 Tars.py

# Démarrer avec une clé API Anthropic
ANTHROPIC_API_KEY=sk-... python3 Tars.py
```

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
- Vérifiez que le port 8000 est libre

### Le frontend ne se connecte pas
- Vérifiez que le backend est en cours d'exécution
- Essayez d'ouvrir `http://localhost:8000` dans un navigateur
- Vérifiez la console du navigateur (F12)

### La reconnaissance vocale ne fonctionne pas
- Utilisez **Chrome** ou **Edge** (Web Speech API nécessaire)
- Autorisez l'accès au micro dans les paramètres du navigateur
- Vérifiez que le micro fonctionne (testez avec un autre site)

### Les clips audio ne se jouent pas
- Vérifiez que les fichiers existent dans `static/acks/`
- Vérifiez que le serveur les sert correctement (`http://localhost:8000/static/acks/court/recu.mp3`)
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
