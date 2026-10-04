# Tars
Tars mais pas tars car j'ai pas les droits d'auteurs et parce que j'ai pas encore d'idée

# Projet : "Tars pas tars", assistant vocal personnel avec personnalité TARS (Interstellar)

## Objectif
Assistant vocal quasi instantané (cible : < 1 s entre la fin de ma phrase et le début de la réponse), avec mémoire persistante et personnage role play : TARS est un équipier sec et ironique, je suis le commandant.

## Pipeline
vocal → STT → texte → LLM (avec accès à des tools) → réponse → TTS → vocal
La mémoire est lue avant la réponse et écrite après.

## Contraintes techniques
- APIs cloud pour STT, LLM et TTS (pas de modèle local, la latence prime).
- Streaming partout (STT, LLM, TTS), connexion WebSocket persistante.
- VAD (détection de fin de parole) en local sur l'appareil.
- Gestion de l'interruption (barge-in) : si je parle pendant la réponse, tout s'arrête net.

## Latence : accusé de réception instantané
- Clips audio préenregistrés (même voix TTS, mêmes réglages que les réponses), joués en local en < 100 ms.
- Déclenchés uniquement si le premier token du LLM n'est pas arrivé après ~250 ms (sinon on ne joue rien).
- Trois familles : court ("Reçu.", "Mmh."), outil ("Je regarde."), réflexion ("Hm. Bonne question.").
- 5 à 10 variantes par famille, tirage aléatoire sans répétition consécutive.
- Pas de chevauchement avec la vraie réponse (file d'attente jusqu'à la fin du clip) ; coupé net si interruption.
- Les clips dépendent du réglage d'humour.

## Personnage et réglages
- Paramètres humour et honnêteté (0-100 %) réglables à l'oral ("TARS, humour à 60 %"), stockés dans la mémoire, persistants.
- TARS répond de façon sèche la plupart du temps ; l'humour n'arrive que sur un silence ou une mauvaise nouvelle.
- Il confirme un changement de réglage dans le personnage.
- Voix TTS un peu plate/métallique pour l'effet robot.
- Idées optionnelles : mode mission (briefings courts, points d'étape, rapport de fin) et journal de bord quotidien à la première personne.

## Mémoire et infra
- Le Raspberry Pi 5 est la source de vérité de la mémoire et reste hors du chemin audio : les appareils (PC, téléphones) parlent directement aux APIs.
- Au démarrage de session, un paquet de contexte (réglages + faits récents) est chargé depuis le Pi dans le prompt ; aucun aller-retour vers le Pi pendant la conversation.
- Écriture mémoire asynchrone, après la réponse vocale.
- Mémoire sous forme de journal append-only d'événements, avec consolidation nocturne sur le Pi en faits propres.

## À trancher
- Cascade STT→LLM→TTS (plus de contrôle sur voix et mémoire) ou API speech-to-speech temps réel (plus rapide, moins de contrôle).
- Mémoire locale sur chaque appareil avec synchro, ou clients légers sans mémoire locale.
- Budget mensuel pour les APIs.

## Hors périmètre
Pas de rapports de statut du Pi, pas de lien avec l'agent Ultron.

## Ce que j'attends de toi
[à compléter : ex. "propose l'architecture détaillée", "écris le code du pipeline en Python", "génère le prompt système du personnage"]