# Icônes TARS

Identité monolithe : quatre barres verticales crème sur fond graphite, avec une LED orange. Le dessin est volontairement sans texte, lisible dès 48 px et aligné sur l'interface (fond clair `#E7E8E6`, encre `#14171A`, accents orange).

## Palette

| Rôle | Couleur | Usage |
|------|---------|-------|
| Fond | `#14171A` | Fond plein de l'icône |
| Barres | `#E7E8E6` | Quatre barres pilule |
| LED | `#E39B2D` | Point de statut sous le monolithe |

## Fichiers

| Fichier | Taille | Usage |
|---------|--------|-------|
| `tars.svg` | 512 × 512 (vectoriel) | Maître de référence |
| `tars-512x512.png` | 512 × 512 | Icône haute résolution |
| `tars-maskable-512x512.png` | 512 × 512 | Maskable, marque dans les 80 % centraux |
| `tars-192x192.png` | 192 × 192 | Android / PWA |
| `apple-touch-icon-180x180.png` | 180 × 180 | Écran d'accueil iOS |
| `favicon-32x32.png` | 32 × 32 | Favicon navigateur |
| `preview.png` | 512 × 512 | Planche de contrôle (tailles réelles, zoom ×4) |
| `generate_icons.py` | — | Générateur reproductible |

## Géométrie

Le maître utilise un `viewBox` de 512 × 512 :

- Barres : largeur 54, rayon 27, espacées de 28, alignées sur une base à `y = 376`.
- Hauteurs : 168, 260, 192 et 216 ; la plus haute commence à `y = 116`.
- LED : cercle de rayon 16 centré en `(256, 420)`.
- Marges : 106 px à gauche et à droite, 116 px en haut, 76 px sous la LED.
- La marque complète tient dans les 80 % centraux exigés pour le maskable.

## Régénération

Depuis la racine du dépôt :

```powershell
python "static\icons\generate_icons.py"
```

Le script requiert Pillow (testé avec Pillow 12.1.1). Il rend chaque taille en suréchantillonnage ×8 puis réduit en Lanczos, et écrit :

- les PNG web dans `static/icons/` ;
- les mipmaps Android dans `android/app/src/main/res/mipmap-*/` ;
- la planche `preview.png`.

Le SVG et les XML Android ne sont pas réécrits : ils partagent les mêmes coordonnées et doivent être ajustés ensemble en cas de modification du dessin.

## Android

- Icône adaptative : `res/mipmap-anydpi-v26/ic_launcher.xml` et `ic_launcher_round.xml`.
- Fond : `@color/ic_launcher_background` (`#14171A`).
- Foreground : `res/drawable/ic_launcher_foreground.xml`, viewport 108 × 108, groupe mis à l'échelle 0,2 et translaté pour garder la marque dans la zone de sécurité 66 × 66 (bornes 24–84 en X, 22–86 en Y).
- Mipmaps legacy : 48, 72, 96, 144 et 192 px. `ic_launcher_round.png` reprend le visuel avec un fond circulaire.
- Manifest : `android:icon="@mipmap/ic_launcher"` et `android:roundIcon="@mipmap/ic_launcher_round"`.

## Web

L'icône n'est pas encore référencée dans `index.html`. Pour l'ajouter :

```html
<link rel="icon" href="/static/icons/favicon-32x32.png" sizes="32x32">
<link rel="icon" href="/static/icons/tars-192x192.png" sizes="192x192">
<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon-180x180.png">
```

## Contrôles

Le générateur vérifie pour chaque PNG : existence, taille attendue, mode RGB/RGBA et fichier non vide. La planche `preview.png` affiche le maître, les tailles réelles 48 et 32 px, un zoom ×4 du rendu 48 px et l'icône 180 px.
