# Clips Audio Originaux de TARS (Interstellar)

Ce dossier est prévu pour stocker les **extraits audio originaux** de TARS du film *Interstellar* (voix de Bill Irwin).

---

## 📥 Où télécharger les clips ?

### Sources officielles (gratuites) :
1. **[101 Soundboards - TARS Interstellar](https://www.101soundboards.com/boards/140263-tars-release-interstellar-soundboard)**
   - Clips comme : *"Affirmative"*, *"Negative"*, *"Yes"*, *"No"*, etc.
   - **Format** : MP3, téléchargeables directement

2. **[SoundCloud - TARS INTERSTELLAR](https://soundcloud.com/user-149832269/tars-interstellar)**
   - Extraits longs (ex: *"ENDURANCE I OUT!"*)

3. **[GitHub Gist - Tous les dialogues de TARS](https://gist.github.com/zacs/a1ea13fb50f667a06cf4d2c722af0eff)**
   - Liste complète des répliques pour référence

---

## 📁 Structure recommandée

```
static/acks/tars_original/
├── affirmative.mp3       # "Affirmative"
├── negative.mp3          # "Negative"
├── yes.mp3              # "Yes"
├── no.mp3               # "No"
├── humor_100.mp3         # "Humor setting: 100%"
├── systems_nominal.mp3   # "Systems nominal"
├── i_am_not_babysitter.mp3 # "I'm an assistant, not a babysitter"
└── README.md             # Ce fichier
```

---

## 🔧 Intégration dans le projet

### 1. Ajouter les clips dans `index.html`
Modifie la section `ACK_AUDIO` (ligne ~140) :

```javascript
const ACK_AUDIO = {
  court: [
    new Audio("/static/acks/tars_original/affirmative.mp3"),
    new Audio("/static/acks/tars_original/systems_nominal.mp3"),
    new Audio("/static/acks/tars_original/yes.mp3")
  ],
  reflexion: [
    new Audio("/static/acks/tars_original/humor_100.mp3"),
    new Audio("/static/acks/tars_original/calculating.mp3")
  ],
  drole: [
    new Audio("/static/acks/tars_original/i_am_not_babysitter.mp3"),
    new Audio("/static/acks/tars_original/sarcasm.mp3")
  ]
};
```

### 2. Mettre à jour `pickAck()`
Aucune modification nécessaire : la logique existante fonctionnera automatiquement.

---

## ⚠️ Notes légales

- **Usage personnel uniquement** : Les extraits audio du film sont protégés par des droits d'auteur.
- **Ne pas redistribuer** : Ne partage pas les clips dans des projets publics sans autorisation.
- **Alternatives libres** : Utilise [ElevenLabs](https://elevenlabs.io/) ou [Piper TTS](https://github.com/rhasspy/piper) pour générer une voix similaire **sans droits d'auteur**.

---

## 🎬 Répliques iconiques à inclure

| Réplique (EN) | Réplique (FR) | Contexte | Fichier suggéré |
|---------------|---------------|----------|------------------|
| "Affirmative" | "Affirmatif" | Réponse positive | `affirmative.mp3` |
| "Negative" | "Négatif" | Réponse négative | `negative.mp3` |
| "Systems nominal" | "Systèmes nominaux" | État normal | `systems_nominal.mp3` |
| "Humor setting: 100%" | "Réglage humour : 100%" | Réglage humour | `humor_100.mp3` |
| "I'm an assistant, not a babysitter" | "Je suis un assistant, pas une baby-sitter" | Sarcasme | `not_babysitter.mp3` |
| "Yes" | "Oui" | Réponse courte | `yes.mp3` |
| "No" | "Non" | Réponse courte | `no.mp3` |
| "Roger that" | "Reçu" | Accusé de réception | `roger_that.mp3` |

---

## 🔗 Liens directs pour téléchargement

- [TARS Soundboard (101 Soundboards)](https://www.101soundboards.com/boards/140263-tars-release-interstellar-soundboard)
- [TARS Interstellar (SoundCloud)](https://soundcloud.com/user-149832269/tars-interstellar)

---

## 🛠️ Génération alternative (sans droits d'auteur)

Si tu préfères éviter les clips du film, utilise **ElevenLabs** pour cloner la voix de TARS :

1. **Crée un compte** sur [ElevenLabs](https://elevenlabs.io/)
2. **Entraîne un modèle** avec des extraits de TARS (ou utilise un modèle existant)
3. **Génère tes propres clips** :
   ```python
   from elevenlabs import generate, play
   audio = generate(
       text="Affirmative, commandant.",
       voice="TARS"  # Ton modèle entraîné
   )
   play(audio)
   ```

---

## 📌 Instructions pour contribuer

1. **Télécharge** les clips depuis les sources ci-dessus
2. **Renomme-les** selon la structure recommandée
3. **Place-les** dans ce dossier (`static/acks/tars_original/`)
4. **Fais un commit** :
   ```bash
   git add static/acks/tars_original/
   git commit -m "feat: Ajout clips audio originaux de TARS"
   git push
   ```

---

*⚠️ Ce dossier est vide par défaut pour éviter les problèmes de droits d'auteur. À toi de l'alimenter !*
