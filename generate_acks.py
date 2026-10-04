#!/usr/bin/env python3
"""
Script pour générer les clips audio des accusés de réception.

Nécessite :
  - gTTS (pour une voix française) : pip install gtts
  - pydub (pour convertir en MP3) : pip install pydub
  - ffmpeg (pour pydub)

OU
  - piper (pour une voix locale) : pip install piper-tts
  - Un modèle Piper français (ex: fr_FR-apho-diphone)

Utilisation :
  python3 generate_acks.py --method gtts    # Utilise gTTS (nécessite internet)
  python3 generate_acks.py --method piper   # Utilise Piper (local)
  python3 generate_acks.py --method dummy   # Génère des fichiers silencieux (pour test)
"""

import os
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static" / "acks"

# Texte des accusés de réception
ACK_TEXT = {
    "court": [
        "Reçu.",
        "Mmh.",
        "Compris.",
        "Bien reçu.",
        "OK."
    ],
    "reflexion": [
        "Hm. Voyons.",
        "Une seconde.",
        "Je réfléchis.",
        "Laissez moi vérifier.",
        "Attendez."
    ],
    "drole": [
        "Reçu. Je fais semblant d'être surpris.",
        "Mmh. Passionnant.",
        "Compris. Évidemment.",
        "Bien reçu. Enfin.",
        "OK. Si vous le dites."
    ]
}

def generate_dummy_clips():
    """Génère des fichiers MP3 silencieux (pour test)"""
    print("Génération de clips audio dummy (silencieux)...")
    for category, texts in ACK_TEXT.items():
        cat_dir = STATIC_DIR / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(texts):
            # Créer un fichier MP3 silencieux (juste pour la structure)
            filename = cat_dir / f"{text.lower().replace(' ', '_').replace('.', '').replace("'", '')}.mp3"
            # Écrire un fichier vide (ou un fichier WAV silencieux minimal)
            with open(filename, "wb") as f:
                # En-tête WAV minimal silencieux (44 octets)
                f.write(b'RIFF\x24\x08\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x02\x00\x44\xac\x00\x00\x10\xb1\x02\x00\x04\x00\x00\x00data\x00\x00\x00\x00')
            print(f"  Créé: {filename}")
    print("Clips dummy générés avec succès !")


def generate_with_gtts():
    """Génère des clips avec gTTS (nécessite internet)"""
    try:
        from gtts import gTTS
        import pydub
        from pydub import AudioSegment
        from pydub.playback import play
    except ImportError as e:
        print(f"Erreur : {e}")
        print("Installez les dépendances : pip install gtts pydub")
        print("Et installez ffmpeg : sudo apt install ffmpeg")
        return False
    
    print("Génération de clips audio avec gTTS...")
    for category, texts in ACK_TEXT.items():
        cat_dir = STATIC_DIR / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for text in texts:
            filename = cat_dir / f"{text.lower().replace(' ', '_').replace('.', '').replace("'", '')}.mp3"
            try:
                # Générer avec gTTS (voix française)
                tts = gTTS(text=text, lang='fr', slow=False)
                tts.save(filename)
                
                # Optionnel : normaliser le volume et convertir en MP3
                # audio = AudioSegment.from_mp3(filename)
                # audio = audio.normalize()
                # audio.export(filename, format="mp3", bitrate="64k")
                
                print(f"  Généré: {filename}")
            except Exception as e:
                print(f"  Erreur pour '{text}': {e}")
    print("Clips gTTS générés avec succès !")
    return True


def generate_with_piper():
    """Génère des clips avec Piper (local, nécessite un modèle)"""
    try:
        import piper
    except ImportError as e:
        print(f"Erreur : {e}")
        print("Installez Piper : pip install piper-tts")
        print("Téléchargez un modèle français :")
        print("  wget https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/apho/diphone/fr_FR-apho-diphone.onnx")
        return False
    
    print("Génération de clips audio avec Piper...")
    
    # Chemin vers le modèle Piper (à adapter)
    model_path = ROOT / "models" / "fr_FR-apho-diphone.onnx"
    if not model_path.exists():
        print(f"Modèle Piper introuvable à {model_path}")
        print("Téléchargez-le depuis : https://huggingface.co/rhasspy/piper-voices/tree/main/fr/fr_FR/apho/diphone")
        return False
    
    # Charger le modèle
    try:
        speaker = piper.PiperVoice.load(model_path)
    except Exception as e:
        print(f"Erreur lors du chargement du modèle : {e}")
        return False
    
    for category, texts in ACK_TEXT.items():
        cat_dir = STATIC_DIR / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for text in texts:
            filename = cat_dir / f"{text.lower().replace(' ', '_').replace('.', '').replace("'", '')}.wav"
            try:
                # Générer avec Piper
                speaker.synthesize(text, str(filename))
                print(f"  Généré: {filename}")
            except Exception as e:
                print(f"  Erreur pour '{text}': {e}")
    print("Clips Piper générés avec succès !")
    return True


def main():
    parser = argparse.ArgumentParser(description="Générer les clips audio pour TARS")
    parser.add_argument("--method", choices=["gtts", "piper", "dummy"], default="dummy",
                        help="Méthode de génération (gtts, piper, dummy)")
    args = parser.parse_args()
    
    if args.method == "gtts":
        generate_with_gtts()
    elif args.method == "piper":
        generate_with_piper()
    else:
        generate_dummy_clips()


if __name__ == "__main__":
    main()
