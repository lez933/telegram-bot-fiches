# bot.py
import csv
import os
import re
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import phonenumbers
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------- Configuration ----------
CSV_PATH_DEFAULT = "./data.csv"
FR_REGION = "FR"
CLEAN_RE = re.compile(r"[^0-9+]")

# ---------- Normalisation des numéros ----------
def normalize_fr(raw: str) -> Optional[str]:
    """Normalise un numéro FR en version nationale (0XXXXXXXXX).
       Essaie plusieurs variantes si la première tentative échoue."""
    if not raw:
        return None
    s = CLEAN_RE.sub("", raw).strip()
    if not s:
        return None

    # Cas 0033 -> +33
    if s.startswith("0033"):
        s = "+" + s[2:]

    attempts = []
    attempts.append(s)
    # si commence par 33 sans +, ajouter +
    if s.startswith("33") and not s.startswith("+"):
        attempts.append("+" + s)
    # si 9 chiffres (sans 0) et commence par 6/7/9 -> essayer avec 0 et +33
    if len(s) == 9 and s[0] in "679":
        attempts.append("0" + s)
        attempts.append("+33" + s)
        attempts.append("0033" + s)
    # si 10 chiffres sans leading 0 -> ajouter 0
    if len(s) == 10 and not s.startswith("0"):
        attempts.append("0" + s)
    # déduplique tout
    seen = set()
    attempts = [a for a in attempts if a and (a not in seen and not seen.add(a))]

    for a in attempts:
        try:
            num = phonenumbers.parse(a, None if a.startswith("+") else FR_REGION)
            if not phonenumbers.is_valid_number(num):
                continue
            national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
            national = CLEAN_RE.sub("", national)
            # s'assurer que les num FR commencent par 0
            if national and not national.startswith("0") and num.country_code == 33:
                national = "0" + national
            return national
        except Exception:
            continue
    return None

# ---------- Chargement et indexation du CSV ----------
def load_index(csv_path: str) -> Tuple[Dict[str, List[Dict[str, str]]], int, int, List[Dict[str, str]]]:
    """
    Charge le CSV. Renvoie :
    - idx: dict clé=numéro_normalisé => [rows]
    - total: nombre total de lignes lues
    - indexed: nombre de fiches contenant au moins un numéro valide
    - all_rows: toutes les lignes telles que lues (list de dict)
    """
    idx: Dict[str, List[Dict[str, str]]] = {}
    total = 0
    indexed = 0
    all_rows: List[Dict[str, str]] = []
    if not os.path.exists(csv_path):
        return idx, total, indexed, all_rows

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # nettoyer clés/valeurs
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            all_rows.append(row)
            total += 1

            # liste large de noms de colonnes possibles contenant un numéro
            nums = []
            for key in ["Mobile","mobile","Telephone Fixe","Téléphone Fixe","Tel","Telephone","telephone",
                        "Phone","phone","Portable","portable","Numero","NumeroTelephone","Numéro","numero_mobile",
                        "telephone_mobile","mobile_phone","gsm","telephone_fix"]:
                if key in row and row[key]:
                    n = normalize_fr(row[key])
                    if n:
                        nums.append(n)
            if not nums:
                continue
            indexed += 1
            for n in nums:
                idx.setdefault(n, []).append(row)
    return idx, total, indexed, all_rows

# ---------- Affichage d'une fiche ----------
def format_card(d: Dict[str, str]) -> str:
    order = ["Civilite","Prenom","Nom","Date de naissance","Email","Mobile","Telephone Fixe",
             "Code Postal","Ville","Adresse","IBAN","BIC"]
    lines = []
    for k in order:
        v = d.get(k, "").strip()
        if v:
            lines.append(f"{k}: {v}")
    # champs restants
    for k, v in d.items():
        if k not in order and v.strip():
            lines.append(f"{k}: {v.strip()}")
    return "\n".join(lines) if lines else "(fiche vide)"

# ---------- Application ----------
class App:
    def __init__(self, token: str, csv_path: str):
        self.token = token
        self.csv_path = csv_path
        self.index: Dict[str, List[Dict[str, str]]] = {}
        self.total = 0
        self.indexed = 0
        self.all_rows: List[Dict[str, str]] = []

    def start(self):
        app = ApplicationBuilder().token(self.token).build()
        # charger l'index au démarrage
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        print(f"CSV chargé: {self.indexed} fiches indexées / {self.total} lignes (source: {self.csv_path}).")

        # handlers
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("reload", self.cmd_reload))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("export", self.cmd_export))
        app.add_handler(CommandHandler("num", self.cmd_num))
        app.add_handler(CommandHandler("load", self.cmd_load))

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.Document.ALL, self.on_document))

        print("Bot démarré. Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
        app.run_polling()

    # ----- commandes -----
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Bonjour ! Envoie-moi un numéro (ex: 06 12 34 56 78).\n"
            "Tu peux aussi m'envoyer des fichiers (.csv/.txt) puis envoyer /load pour les ajouter au data.csv.\n"
            "Commandes: /help /reload /stats /export /num <numéro> /load"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "<b>Utilisation</b> :\n"
            "• Envoie un numéro (06..., +33...)\n"
            "• Ou envoie les 4 derniers chiffres\n\n"
            "<b>Commandes</b> :\n"
            "• /reload → recharge le CSV\n"
            "• /stats → nombre de fiches indexées\n"
            "• /export → envoie toutes les fiches en .txt\n"
            "• /num <numéro> → cherche et renvoie la/les fiche(s)\n"
            "• /load → intègre le(s) fichier(s) que tu as uploadés\n",
            parse_mode=ParseMode.HTML
        )

    async def cmd_reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        msg = f"CSV rechargé: {self.indexed} fiches indexées / {self.total} lignes."
        print(msg)
        await update.message.reply_text(msg)

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Fiches chargées: {self.indexed} / {self.total} lignes.")

    async def cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.all_rows:
            await update.message.reply_text("Aucune fiche à exporter (CSV vide ?).")
            return
        # dédup
        seen = set()
        unique_rows: List[Dict[str, str]] = []
        for r in self.all_rows:
            key = tuple(sorted(r.items()))
            if key not in seen:
                seen.add(key)
                unique_rows.append(r)
        parts = []
        for i, row in enumerate(unique_rows, start=1):
            parts.append(f"Fiche {i}\n----------------\n{format_card(row)}")
        content = "\n\n".join(parts)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"fiches_export_{stamp}.txt"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tf:
            tf.write(content)
            tmp_path = tf.name
        try:
            with open(tmp_path, "rb") as f:
                await update.message.reply_document(document=f, filename=fname, caption="Export des fiches")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    async def cmd_num(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args if hasattr(context, "args") else []
        query = " ".join(args).strip()
        if not query:
            await update.message.reply_text("Utilisation : /num <numéro> (ex: /num 0612345678 ou /num 1234)")
            return
        await self._reply_with_results(update, query)

    # ----- réception de texte -----
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        txt = (update.message.text or "").strip()
        # permet d'envoyer plusieurs numéros séparés par , ; ou ligne
        queries = [t for t in re.split(r"[\n,;]", txt) if t.strip()]
        for q in queries:
            await self._reply_with_results(update, q)

    # ----- réception de fichiers -----
    async def on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        doc = update.message.document
        if not doc:
            await update.message.reply_text("Aucun fichier détecté.")
            return

        uploads_dir = os.path.join(os.getcwd(), "uploads")
        os.makedirs(uploads_dir, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{stamp}_{doc.file_name}"
        dest_path = os.path.join(uploads_dir, filename)

        try:
            file = await doc.get_file()
            await file.download_to_drive(dest_path)
        except Exception as e:
            await update.message.reply_text(f"Erreur lors du téléchargement du fichier: {e}")
            return

        chat_id = update.effective_chat.id
        key = f"uploads_{chat_id}"
        lst = context.application.bot_data.get(key, [])
        lst.append(dest_path)
        context.application.bot_data[key] = lst

        await update.message.reply_text(
            f"Fichier reçu: {doc.file_name}\nEnregistré. Envoie maintenant /load pour le traiter."
        )

    # ----- commande /load -----
    async def cmd_load(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        key = f"uploads_{chat_id}"
        uploads = context.application.bot_data.get(key, [])

        if not uploads:
            await update.message.reply_text("Aucun fichier à charger. Envoie d'abord un fichier au bot.")
            return

        added_lines = 0
        # créer data.csv s'il n'existe pas
        if not os.path.exists(self.csv_path):
            open(self.csv_path, "a", encoding="utf-8").close()

        for up in uploads:
            try:
                with open(up, "r", encoding="utf-8", errors="replace") as fsrc, \
                     open(self.csv_path, "a", encoding="utf-8") as fdst:
                    written = 0
                    for line in fsrc:
                        if line.strip() == "":
                            continue
                        fdst.write(line.rstrip("\n") + "\n")
                        written += 1
                    added_lines += written
            except Exception as e:
                await update.message.reply_text(f"Erreur lecture {os.path.basename(up)} : {e}")

        # vider la liste d'uploads pour ce chat
        context.application.bot_data[key] = []

        # recharger index
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        msg = f"✅ {added_lines} fiches ajoutées (approx.). Total: {self.total}"
        await update.message.reply_text(msg)

    # ----- recherche et réponse -----
    async def _reply_with_results(self, update: Update, q: str):
        normalized = normalize_fr(q)
        results: List[Dict[str, str]] = []
        if normalized and normalized in self.index:
            results = self.index[normalized]
        else:
            last4 = re.sub(r"\D", "", q)[-4:]
            if len(last4) == 4:
                for k, v in self.index.items():
                    if k.endswith(last4):
                        results.extend(v)

        if not results:
            await update.message.reply_text(
                f"Aucune fiche trouvée pour: <code>{q}</code>", parse_mode=ParseMode.HTML
            )
            return

        # dédupe
        seen = set()
        uniq: List[Dict[str, str]] = []
        for r in results:
            key = tuple(sorted(r.items()))
            if key not in seen:
                seen.add(key)
                uniq.append(r)

        if len(uniq) == 1:
            await update.message.reply_text(format_card(uniq[0]))
        else:
            parts = []
            for i, r in enumerate(uniq, 1):
                parts.append(f"Fiche {i}\n----------------\n{format_card(r)}")
            await update.message.reply_text("\n\n".join(parts))

# ---------- Entrée ----------
def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    csv_path = os.getenv("CSV_PATH", CSV_PATH_DEFAULT)
    if not token:
        raise SystemExit("Veuillez éditer les variables d'environnement et définir BOT_TOKEN=...")
    if not os.path.exists(csv_path):
        # create empty CSV file to avoid crashes
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("")
    App(token, csv_path).start()

if __name__ == "__main__":
    main()
