# Icônes TARS

Ce dossier contient les icônes pour l'application TARS.

---

## 📁 Fichiers disponibles

| Fichier | Format | Taille | Utilisation |
|---------|--------|-------|-------------|
| `tars.svg` | SVG vectoriel | - | Icône principale (toutes tailles) |
| `tars-192x192.png` | PNG | 192x192 | Icône pour Android/Windows |
| `tars-512x512.png` | PNG | 512x512 | Icône haute résolution |

---

## 🎨 Design de l'icône

L'icône représente le **monolithe de TARS** avec :
- Un **rectangle noir** (corps du monolithe)
- **4 lignes verticales** (design caractéristique de TARS)
- **3 lignes horizontales** (détails du monolithe)
- Un **point vert** en haut (indicateur de statut)
- Le texte **"TARS"** en vert fluo

**Couleurs** :
- Fond : `#111111` (noir profond)
- Lignes : `#00ff88` (vert fluo, comme dans l'interface)
- Texte : `#00ff88` (vert fluo)

---

## 📥 Génération des icônes PNG

### Depuis le SVG
Utilise **Inkscape** ou **ImageMagick** pour générer les PNG :

#### Avec ImageMagick :
```bash
# 192x192
convert -background none -resize 192x192 static/icons/tars.svg static/icons/tars-192x192.png

# 512x512
convert -background none -resize 512x512 static/icons/tars.svg static/icons/tars-512x512.png

# Autres tailles (pour favicon, etc.)
convert -background none -resize 32x32 static/icons/tars.svg static/icons/tars-32x32.png
convert -background none -resize 64x64 static/icons/tars.svg static/icons/tars-64x64.png
convert -background none -resize 128x128 static/icons/tars.svg static/icons/tars-128x128.png
```

#### Avec Inkscape :
```bash
inkscape static/icons/tars.svg --export-png=static/icons/tars-192x192.png -w 192 -h 192
inkscape static/icons/tars.svg --export-png=static/icons/tars-512x512.png -w 512 -h 512
```

---

## 📌 Utilisation dans l'application

### Pour Android (Capacitor)
1. Place `tars-192x192.png` dans `android/app/src/main/res/mipmap-xxxhdpi/`
2. Renomme-le en `ic_launcher.png`
3. Utilise [Android Asset Studio](https://romannurik.github.io/AndroidAssetStudio/) pour générer les autres densités

### Pour Windows (Electron)
Dans `package.json` :
```json
"build": {
  "win": {
    "icon": "static/icons/tars-512x512.png"
  }
}
```

### Pour le Web (favicon)
Dans `index.html` :
```html
<link rel="icon" href="/static/icons/tars-32x32.png" sizes="32x32">
<link rel="icon" href="/static/icons/tars-192x192.png" sizes="192x192">
<link rel="apple-touch-icon" href="/static/icons/tars-192x192.png">
```

---

## 🎯 Tailles recommandées

| Plateforme | Taille | Fichier |
|------------|-------|---------|
| Favicon | 32x32 | `tars-32x32.png` |
| Android (mdpi) | 48x48 | `tars-48x48.png` |
| Android (hdpi) | 72x72 | `tars-72x72.png` |
| Android (xhdpi) | 96x96 | `tars-96x96.png` |
| Android (xxhdpi) | 144x144 | `tars-144x144.png` |
| Android (xxxhdpi) | 192x192 | `tars-192x192.png` |
| iOS | 180x180 | `tars-180x180.png` |
| Windows | 256x256 | `tars-256x256.png` |
| Haute résolution | 512x512 | `tars-512x512.png` |

---

## 🔧 Outils utiles

- **[Favicon Generator](https://realfavicongenerator.net/)** : Génère toutes les tailles nécessaires
- **[Android Asset Studio](https://romannurik.github.io/AndroidAssetStudio/)** : Génère les icônes Android
- **[ImageMagick](https://imagemagick.org/)** : Outil en ligne de commande pour convertir les images

---

## 📝 Notes

- Le SVG est **modifiable** : tu peux ajuster les couleurs, les tailles ou les détails.
- Pour un **effet glow**, ajoute un filtre SVG comme dans le code.
- Les icônes PNG doivent avoir un **fond transparent** pour une meilleure intégration.
