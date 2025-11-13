
GUIDE SUPER SIMPLE (Windows)
============================
1) Installe Python 3.10+ depuis https://www.python.org/downloads/
   → Coche "Add Python to PATH" à l'installation.
2) Ouvre ce dossier dans l'Explorateur Windows.
3) Dans la barre d'adresse, tape: cmd  (puis Entrée) → un terminal s'ouvre ici.
4) Tape cette commande pour installer les dépendances :
       pip install -r requirements.txt
5) Ouvre le fichier .env et remplace BOT_TOKEN par le token reçu de @BotFather.
6) Mets tes fiches dans data.csv (tu peux garder les colonnes existantes ou en ajouter).
7) Lance le bot :
       python bot.py
8) Dans Telegram, cherche ton bot (le nom d'utilisateur qui finit par 'bot'), clique Start
   et envoie un numéro (ex: 06 12 34 56 78).

Astuces:
- Pour relancer le bot après avoir modifié le CSV: /reload
- Pour savoir combien de fiches sont lues: /stats

⚠️ Données personnelles (RGPD) : tu es responsable des données que tu charges ici.
