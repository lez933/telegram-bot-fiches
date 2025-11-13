# bot.py (version DEMO pour tests, données fictives)
# Utilisation pédagogique : remplace dans ton repo pour tester le comportement.
# NE PAS y mettre de vraies données personnelles dans le code.

import os
import csv
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
KV_RE = re.compile(r"^\s*([^:]+)\s*:\s*(.*)$")  # pour parser "Clé : Valeur"

# ---------- Normalisation ----------
def normalize_fr(raw: str) -> Optional[str]:
    """Normalise un numéro FR en version nationale 0XXXXXXXXX (essaie plusieurs variantes)."""
    if not raw:
        return None
    s = CLEAN_RE.sub("", raw).strip()
    if not s:
        return None
    if s.startswith("0033"):
        s = "+" + s[2:]

    attempts = [s]
    if s.startswith("33") and not s.startswith("+"):
        attempts.append("+" + s)
    if len(s) == 9 and s[0] in "679":
        attempts.append("0" + s)
        attempts.append("+33" + s)
    if len(s) == 10 and not s.startswith("0"):
        attempts.append("0" + s)

    seen = set()
    attempts = [a for a in attempts if a and (a not in seen and not seen.add(a))]

    for a in attempts:
        try:
            num = phonenumbers.parse(a, None if a.startswith("+") else FR_REGION)
            if not phonenumbers.is_valid_number(num):
                continue
            national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
            national = CLEAN_RE.sub("", national)
            if national and not national.startswith("0") and num.country_code == 33:
                national = "0" + national
            return national
        except Exception:
            continue
    return None

# ---------- Chargement / indexation ----------
def load_index(csv_path: str) -> Tuple[Dict[str, List[Dict[str, str]]], int, int, List[Dict[str, str]]]:
    """
    Charge le CSV indiqué et renvoie :
    - index par numéro normalisé -> [rows]
    - total lignes lues
    - indexed (lignes contenant au moins un numéro)
    - all_rows list of dicts
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
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            all_rows.append(row)
            total += 1

            nums = []
            for key in ["Mobile","mobile","Telephone","telephone","Tel","Phone","Portable","Numero","Numéro",
                        "telephone_mobile","mobile_phone","gsm"]:
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

# ---------- Format affichage ----------
def format_card(d: Dict[str, str]) -> str:
    order = ["Prenom","Nom","Email","Mobile","Telephone","Ville","Adresse"]
    lines = []
    for k in order:
        v = d.get(k, "").strip()
        if v:
            lines.append(f"{k}: {v}")
    for k, v in d.items():
        if k not in order and v.strip():
            lines.append(f"{k}: {v.strip()}")
    return "\n".join(lines) if lines else "(aucune info)"

# ---------- App bot ----------
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
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        print(f"[DEMO] CSV chargé: {self.indexed} fiches indexées / {self.total} lignes (source: {self.csv_path}).")

        # handlers
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("export", self.cmd_export))
        app.add_handler(CommandHandler("num", self.cmd_num))
        app.add_handler(CommandHandler("load", self.cmd_load))
        app.add_handler(CommandHandler("sample", self.cmd_sample))  # génère des données factices

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.Document.ALL, self.on_document))

        print("[DEMO] Bot démarré. Polling...")
        app.run_polling()

    # ----- commandes -----
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Bot DEMO — Envoie-moi un fichier texte structuré (Clé : Valeur) ou use /sample pour créer des fiches factices.\n"
            "Commandes : /help /sample /load /stats /export /num <num>"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Utilisation (DEMO):\n"
            "• Envoie un fichier .txt structuré (Clé : Valeur) puis /load\n"
            "• /sample → crée 2 fiches factices pour tester\n"
            "• /num <numéro> → recherche par numéro (ex: /num 0611223344)\n"
            "• /stats → affiche nombre de fiches indexées\n"
            "• /export → exporte toutes les fiches en .txt\n"
        )

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Fiches indexées: {self.indexed} / {self.total} lignes (source: {self.csv_path}).")

    async def cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.all_rows:
            await update.message.reply_text("Aucune fiche à exporter.")
            return
        parts = []
        for i, row in enumerate(self.all_rows, 1):
            parts.append(f"Fiche {i}\n----------------\n{format_card(row)}")
        content = "\n\n".join(parts)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"demo_export_{stamp}.txt"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tf:
            tf.write(content)
            tmp_path = tf.name
        try:
            with open(tmp_path, "rb") as f:
                await update.message.reply_document(document=f, filename=fname, caption="Export DEMO")
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    async def cmd_num(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args if hasattr(context, "args") else []
        query = " ".join(args).strip()
        if not query:
            await update.message.reply_text("Utilisation : /num <numéro>")
            return
        await self._reply_with_results(update, query)

    # ----- réception texte -----
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        txt = (update.message.text or "").strip()
        queries = [t for t in re.split(r"[\n,;]", txt) if t.strip()]
        for q in queries:
            await self._reply_with_results(update, q)

    # ----- réception fichier -----
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
            await update.message.reply_text(f"Erreur téléchargement: {e}")
            return

        chat_id = update.effective_chat.id
        key = f"uploads_{chat_id}"
        lst = context.application.bot_data.get(key, [])
        lst.append(dest_path)
        context.application.bot_data[key] = lst

        await update.message.reply_text(f"Fichier reçu: {doc.file_name}\nEnregistré. Envoie /load pour le traiter.")

    # ----- /load -----
    async def cmd_load(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        key = f"uploads_{chat_id}"
        uploads = context.application.bot_data.get(key, [])

        if not uploads:
            await update.message.reply_text("Aucun fichier à charger. Envoie d'abord un fichier.")
            return

        # assure data.csv existe
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", encoding="utf-8") as f:
                f.write("")

        all_new_rows = []
        columns = set()

        for up in uploads:
            name = os.path.basename(up).lower()
            try:
                if name.endswith(".csv"):
                    # on ajoute simplement le csv (ligne par ligne)
                    with open(up, "r", encoding="utf-8", errors="replace") as fsrc, \
                         open(self.csv_path, "a", encoding="utf-8") as fdst:
                        for line in fsrc:
                            if line.strip():
                                fdst.write(line.rstrip("\n") + "\n")
                    continue

                # parser texte "Clé : Valeur" en blocs
                with open(up, "r", encoding="utf-8", errors="replace") as f:
                    current = {}
                    for raw in f:
                        line = raw.strip()
                        if not line:
                            continue
                        if line.startswith("-") and len(line) > 5:
                            if current:
                                all_new_rows.append(current)
                                columns.update(current.keys())
                                current = {}
                            continue
                        m = KV_RE.match(line)
                        if m:
                            k = m.group(1).strip()
                            v = m.group(2).strip()
                            current[k] = v
                    if current:
                        all_new_rows.append(current)
                        columns.update(current.keys())
            except Exception as e:
                await update.message.reply_text(f"Erreur lecture {os.path.basename(up)} : {e}")

        # vider uploads
        context.application.bot_data[key] = []

        # écrire les nouvelles lignes dans data.csv
        if all_new_rows:
            cols = sorted(columns)
            # si data.csv a header existant ? (simple check)
            had_header = False
            try:
                with open(self.csv_path, "r", encoding="utf-8") as f:
                    first = f.readline()
                    if first and "," in first:
                        had_header = True
            except Exception:
                had_header = False

            if not had_header:
                with open(self.csv_path, "a", newline="", encoding="utf-8") as out:
                    writer = csv.DictWriter(out, fieldnames=cols)
                    writer.writeheader()
                    writer.writerows(all_new_rows)
            else:
                # append rows (may mis-align columns if headers diffèrent; demo seulement)
                with open(self.csv_path, "a", newline="", encoding="utf-8") as out:
                    writer = csv.DictWriter(out, fieldnames=cols)
                    writer.writerows(all_new_rows)

        # recharger index
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        await update.message.reply_text(f"✅ {len(all_new_rows)} fiches converties et ajoutées. Total: {self.total}")

    # ----- commande sample (crée données fictives) -----
    async def cmd_sample(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        sample_rows = [
            {"Prenom": "Jean", "Nom": "Dupont", "Mobile": "0611223344", "Ville": "Paris"},
            {"Prenom": "Paul", "Nom": "Martin", "Mobile": "+33 6 11 22 33 44", "Ville": "Lyon"},
        ]
        # écrire sample dans data.csv (écrase pour la demo)
        cols = sorted({k for r in sample_rows for k in r.keys()})
        with open(self.csv_path, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=cols)
            writer.writeheader()
            writer.writerows(sample_rows)

        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        await update.message.reply_text(f"✅ Sample créé: {len(sample_rows)} fiches. Teste /num 0611223344")

    # ----- recherche -----
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
            await update.message.reply_text(f"Aucune fiche trouvée pour: <code>{q}</code>", parse_mode=ParseMode.HTML)
            return

        # dédup
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
    load_dotenv()  # charge .env local si présent
    token = os.getenv("BOT_TOKEN", "").strip()
    csv_path = os.getenv("CSV_PATH", CSV_PATH_DEFAULT)
    if not token:
        print("ERREUR: BOT_TOKEN non défini. Définis la variable d'environnement BOT_TOKEN avant de lancer.")
        return
    # create empty csv if missing (demo)
    if not os.path.exists(csv_path):
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("")
    App(token, csv_path).start()

if __name__ == "__main__":
    main()
