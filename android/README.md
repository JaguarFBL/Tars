# TARS pas tars - Application Android

## Structure
```
android/
├── capacitor.config.json  # Configuration Capacitor
├── package.json           # Dépendances Node.js
├── www/                   # Frontend (index.html + static)
│   ├── index.html
│   ├── capacitor.config.json
│   └── static/
└── app/                   # Code natif Android
    └── src/
        └── main/
            ├── java/com/example/tars/
            │   ├── TarsPlugin.java      # Plugin pour gérer le backend
            │   ├── TarsWidget.java      # Widget natif
            │   └── TarsWidgetUpdateService.java
            ├── res/
            │   ├── layout/tars_widget.xml
            │   ├── xml/tars_widget_info.xml
            │   └── values/strings.xml
            └── AndroidManifest.xml
```

## Prérequis
1. Node.js (pour Capacitor)
2. Android Studio (pour builder l'APK)
3. Un appareil Android (ou émulateur) avec API 21+
4. Termux (optionnel, pour exécuter le backend Python)

## Installation

### 1. Installer Capacitor
```bash
cd android
npm install
```

### 2. Ajouter la plateforme Android
```bash
npx cap add android
```

### 3. Copier les fichiers du frontend
```bash
# Depuis la racine du projet
cp index.html android/www/
cp -r static android/www/
```

### 4. Synchroniser avec Capacitor
```bash
cd android
npx cap sync android
```

### 5. Ouvrir dans Android Studio
```bash
npx cap open android
```
→ Ouvre Android Studio avec le projet configuré

### 6. Builder l'APK
- Dans Android Studio, cliquez sur **Build > Build Bundle(s) / APK(s) > Build APK**
- L'APK sera générée dans `android/app/build/outputs/apk/debug/`

## Utilisation

### Avec Termux (recommandé)
1. Installez [Termux](https://termux.com/) sur votre appareil
2. Dans Termux, installez Python :
   ```bash
   pkg update && pkg upgrade
   pkg install python
   pip install --upgrade pip
   ```
3. Copiez `Tars.py` dans Termux :
   ```bash
   termux-setup-storage
   cp /sdcard/Download/Tars.py ~/../usr/bin/
   ```
4. Installez l'APK générée
5. L'application démarrera Termux pour exécuter le backend

### Sans Termux (alternative)
- Utilisez **Chaquopy** pour intégrer Python directement dans l'APK
- Modifiez `android/app/build.gradle` pour ajouter Chaquopy
- Voir : https://chaquo.com/chaquopy/

## Widget
Le widget est automatiquement inclus dans l'APK et affichera :
- L'état actuel de TARS (off, listening, thinking, speaking)
- Un bouton pour démarrer/arrêter la session

## Dépannage

### L'application ne se connecte pas au backend
- Vérifiez que Termux est installé
- Exécutez `python3 Tars.py` manuellement dans Termux pour tester
- Vérifiez que le port 8000 est accessible

### Le widget ne se met pas à jour
- Vérifiez que le backend est en cours d'exécution
- Vérifiez que le service `TarsWidgetUpdateService` est démarré
- Essayez d'ouvrir `http://localhost:8000/widget` dans un navigateur sur l'appareil

### Problèmes avec Capacitor
- Exécutez `npx cap sync android` pour resynchroniser
- Vérifiez que tous les plugins sont correctement enregistrés dans `AndroidManifest.xml`

## Notes
- Le backend doit être exécuté séparément (via Termux ou Chaquopy)
- Le widget se met à jour toutes les secondes
- Pour une expérience optimale, utilisez un appareil avec Android 10+
