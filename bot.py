
import os
import re
import csv
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
import phonenumbers
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- Configuration ----------------
CSV_PATH_DEFAULT = "./data.csv"
FR_REGION = "FR"
CLEAN_RE = re.compile(r"[^0-9+]")
KV_RE = re.compile(r"^\s*([^:]+)\s*:\s*(.*)$")  # pour parser "Clé : Valeur"

# ---------------- Normalisation ----------------
def normalize_fr(raw: str) -> Optional[str]:
    """Normalise un numéro FR pour qu’il devienne 0XXXXXXXXX (ou None si invalide)."""
    if not raw:
        return None
    s = CLEAN_RE.sub("", raw).strip()
    if not s:
        return None

    # 0033 -> +33
    if s.startswith("0033"):
        s = "+" + s[2:]

    # convertir +33... ou 33... en 0...
    if s.startswith("+33"):
        s = "0" + s[3:]
    elif s.startswith("33"):
        s = "0" + s[2:]
    # si déjà 0XXXXXXXXX et bonne longueur -> ok
    elif s.startswith("0") and len(s) == 10:
        pass
    # si 9 chiffres (sans 0) -> ajoute 0 si commence par 6/7/9
    elif len(s) == 9 and s[0] in "679":
        s = "0" + s
    # si plus long -> garder les 10 derniers chiffres
    if len(s) > 10:
        s = s[-10:]

    # vérifie forme finale
    if len(s) != 10 or not s.startswith("0"):
        return None
    return s

# ---------------- Chargement / indexation ----------------
def load_index(csv_path: str) -> Tuple[Dict[str, List[Dict[str, str]]], int, int, List[Dict[str, str]]]:
    """
    Charge le CSV indiqué et renvoie :
      - idx: dict numéro_normalisé -> [rows]
      - total: total lignes lues
      - indexed: lignes contenant au moins un numéro
      - all_rows: toutes les lignes lues (list of dict)
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
            # noms de colonnes courants à vérifier
            for key in ["Mobile","mobile","Telephone","telephone","Tel","Phone","Portable","Numero","Numéro",
                        "telephone_mobile","mobile_phone","gsm","telephone_fix","Telephone Fixe","Téléphone Fixe"]:
                if key in row and row[key]:
                    n = normalize_fr(row[key])
                    if n:
                        nums.append(n)
            if not nums:
                continue
            indexed += 1
            for n in nums:
                idx.setdefault(n, []).append(row)
    # debug minimal: print exemples
    print(f"[INFO] load_index: {indexed} fiches indexées / {total} lignes (source={csv_path}).")
    return idx, total, indexed, all_rows

# ---------------- Format affichage ----------------
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

# ---------------- Bot application ----------------
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
        # charge index au démarrage
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        print(f"[BOT] Démarrage: {self.indexed} fiches indexées / {self.total} lignes.")

        # handlers
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("reload", self.cmd_reload))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("export", self.cmd_export))
        app.add_handler(CommandHandler("num", self.cmd_num))
        app.add_handler(CommandHandler("load", self.cmd_load))
        app.add_handler(CommandHandler("sample", self.cmd_sample))

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.Document.ALL, self.on_document))

        print("[BOT] Bot prêt. Lancement du polling...")
        app.run_polling()

    # ----- commandes -----
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Bonjour — bot DE TEST.\n"
            "Envoie un fichier .txt structuré (Clé : Valeur) puis /load pour le traiter.\n"
            "Commandes: /help /sample /load /reload /stats /export /num <num>"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Utilisation :\n"
            "• Envoyer un fichier .txt structuré (Clé : Valeur) puis /load\n"
            "• /sample → crée 2 fiches factices\n"
            "• /num <num> → recherche un numéro (ex: /num 0611223344)\n"
            "• /reload → recharge le CSV\n"
            "• /stats → affiche nombre indexé\n"
            "• /export → exporte toutes les fiches en .txt\n"
        )

    async def cmd_reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        await update.message.reply_text(f"CSV rechargé: {self.indexed} fiches indexées / {self.total} lignes.")

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Fiches indexées: {self.indexed} / {self.total} lignes.")

    async def cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.all_rows:
            await update.message.reply_text("Aucune fiche à exporter.")
            return
        parts = []
        for i, row in enumerate(self.all_rows, 1):
            parts.append(f"Fiche {i}\n----------------\n{format_card(row)}")
        content = "\n\n".join(parts)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"export_{stamp}.txt"
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
            await update.message.reply_text("Utilisation : /num <numéro>")
            return
        await self._reply_with_results(update, query)

    # ----- reception texte (message libre) -----
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        txt = (update.message.text or "").strip()
        queries = [t for t in re.split(r"[\n,;]", txt) if t.strip()]
        for q in queries:
            await self._reply_with_results(update, q)

    # ----- reception fichier -----
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

    # ----- /load : conversion et ajout au CSV -----
    async def cmd_load(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        key = f"uploads_{chat_id}"
        uploads = context.application.bot_data.get(key, [])

        if not uploads:
            await update.message.reply_text("Aucun fichier à charger. Envoie d'abord un fichier au bot.")
            return

        # s'assurer que data.csv existe
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", encoding="utf-8") as f:
                f.write("")

        all_new_rows = []
        columns = set()

        for up in uploads:
            name = os.path.basename(up).lower()
            try:
                if name.endswith(".csv"):
                    # ajoute simplement le csv (ligne par ligne)
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
                        # séparation par ligne de tirets
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

        # vider la liste d'uploads pour ce chat
        context.application.bot_data[key] = []

        # écrire all_new_rows dans data.csv
        if all_new_rows:
            cols = sorted(columns)
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
                with open(self.csv_path, "a", newline="", encoding="utf-8") as out:
                    writer = csv.DictWriter(out, fieldnames=cols)
                    writer.writerows(all_new_rows)

        # recharger index
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        await update.message.reply_text(f"✅ {len(all_new_rows)} fiches converties et ajoutées. Total: {self.total}")

    # ----- sample : écrit 2 fiches factices pour tester -----
    async def cmd_sample(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        sample_rows = [
            {"Prenom": "Jean", "Nom": "Dupont", "Mobile": "0611223344", "Ville": "Paris"},
            {"Prenom": "Paul", "Nom": "Martin", "Mobile": "+33 6 11 22 33 44", "Ville": "Lyon"},
        ]
        cols = sorted({k for r in sample_rows for k in r.keys()})
        with open(self.csv_path, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=cols)
            writer.writeheader()
            writer.writerows(sample_rows)
        self.index, self.total, self.indexed, self.all_rows = load_index(self.csv_path)
        await update.message.reply_text(f"✅ Sample créé: {len(sample_rows)} fiches. Teste /num 0611223344")

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

# ---------------- Entrée ----------------
def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    csv_path = os.getenv("CSV_PATH", CSV_PATH_DEFAULT)
    if not token:
        raise SystemExit("Erreur: définis la variable d'environnement BOT_TOKEN avant de lancer.")
    if not os.path.exists(csv_path):
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("")
    App(token, csv_path).start()

if __name__ == "__main__":
    main()
