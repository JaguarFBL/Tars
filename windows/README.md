# TARS pas tars - Application Windows

## Structure
```
windows/
├── package.json          # Configuration Electron
├── main.js              # Point d'entrée Electron
├── preload.js           # Pré-chargement pour Electron
├── index.html           # Interface web (copiée depuis la racine)
├── static/              # Fichiers statiques (clips audio)
├── Tars.exe             # Backend (à générer avec PyInstaller)
├── TarsWidget.ini       # Widget Rainmeter
└── TarsWidget.lua       # Script Lua pour le widget
```

## Prérequis
1. Node.js (pour Electron)
2. Python 3.8+
3. PyInstaller (pour packager le backend)
4. Rainmeter (pour le widget, optionnel)

## Installation

### 1. Installer les dépendances
```bash
cd windows
npm install
```

### 2. Générer Tars.exe
```bash
# Depuis la racine du projet
pip install pyinstaller
pyinstaller --onefile --windowed Tars.py
cp dist/Tars.exe windows/
```

### 3. Tester l'application
```bash
cd windows
npm start
```

### 4. Builder l'installateur Windows
```bash
cd windows
npm run dist
```
→ Génère un installateur dans `windows/dist/`

## Utilisation

### Application Electron
- Lancez `Tars Setup 1.0.0.exe` pour installer l'application
- L'application démarre automatiquement le backend (`Tars.exe`)
- Accédez à l'interface via la fenêtre Electron

### Widget Rainmeter
1. Installez [Rainmeter](https://www.rainmeter.net/)
2. Copiez le dossier `windows/` dans `Documents\Rainmeter\Skins\Tars\`
3. Dans Rainmeter, chargez le skin `Tars\TarsWidget.ini`
4. Le widget affichera l'état de TARS et permettra de démarrer/arrêter le backend

## Dépannage

### Le backend ne démarre pas
- Vérifiez que `Tars.exe` existe dans le dossier `windows/`
- Exécutez `Tars.exe` manuellement pour voir les erreurs
- Assurez-vous que le port 8000 est libre

### Le widget ne se met pas à jour
- Vérifiez que le backend est en cours d'exécution
- Vérifiez que Rainmeter peut accéder à `http://localhost:8000/widget`
- Essayez d'ouvrir `http://localhost:8000/widget` dans un navigateur

### Problèmes avec Electron
- Vérifiez que Node.js est installé
- Exécutez `npm install` pour réinstaller les dépendances
- Consultez les logs avec `npm start`

## Notes
- Le backend (`Tars.exe`) doit être dans le même dossier que `main.js`
- Le widget Rainmeter nécessite que le backend soit en cours d'exécution
- Pour un déploiement final, incluez `Tars.exe` dans les ressources de l'application Electron
