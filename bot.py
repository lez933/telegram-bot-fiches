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

CSV_PATH_DEFAULT = "./data.csv"
FR_REGION = "FR"
CLEAN_RE = re.compile(r"[^0-9+]")

def normalize_fr(raw: str) -> Optional[str]:
    """Normalise un numéro FR en version nationale (0XXXXXXXXX)."""
    if not raw:
        return None
    s = CLEAN_RE.sub("", raw).strip()
    if not s:
        return None
    if s.startswith("0033"):
        s = "+" + s[2:]
    try:
        num = phonenumbers.parse(s, None if s.startswith("+") else FR_REGION)
        if not phonenumbers.is_valid_number(num):
            return None
        national = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.NATIONAL)
        national = CLEAN_RE.sub("", national)
        if national and not national.startswith("0") and num.country_code == 33:
            national = "0" + national
        return national
    except Exception:
        return None

def load_index(csv_path: str) -> Tuple[Dict[str, List[Dict[str, str]]], int, int, List[Dict[str, str]]]:
    """Charge le CSV. Renvoie (index par numéro, total, indexés, toutes les lignes)."""
    idx: Dict[str, List[Dict[str, str]]] = {}
    total = 0
    indexed = 0
    all_rows: List[Dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): (v or "").strip() for k, v in row.items()}
            all_rows.append(row)
            total += 1
            nums = []
            for key in ["Mobile","Telephone Fixe","Téléphone Fixe","Tel","Telephone","Phone","Portable","Numero","Numéro"]:
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

def format_card(d: Dict[str, str]) -> str:
    order = ["Civilite","Prenom","Nom","Date de naissance","Email","Mobile","Telephone Fixe",
             "Code Postal","Ville","Adresse","IBAN","BIC"]
    lines = []
    for k in order:
        v = d.get(k, "").strip()
        if v:
            lines.append(f"{k}: {v}")
    for k, v in d.items():
        if k not in order and v.strip():
            lines.append(f"{k}: {v.strip()}")
    return "\n".join(lines) if lines else "(fiche vide)"

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
        print(f"CSV chargé: {self.indexed} fiches indexées / {self.total} lignes (source: {self.csv_path}).")

        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("reload", self.cmd_reload))
        app.add_handler(CommandHandler("stats", self.cmd_stats))
        app.add_handler(CommandHandler("export", self.cmd_export))
        app.add_handler(CommandHandler("num", self.cmd_num))          # 👈 NOUVEAU
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

        print("Bot démarré. Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
        app.run_polling()

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Bonjour ! Envoie-moi un numéro (ex: 06 12 34 56 78).\n"
            "Commandes: /help /reload /stats /export /num <numéro>"
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "<b>Utilisation</b> :\n"
            "• Numéro exact (06..., +33 6..., 0033...)\n"
            "• Ou 4 derniers chiffres\n\n"
            "<b>Commandes</b> :\n"
            "• /reload → recharge le CSV\n"
            "• /stats → nombre de fiches indexées\n"
            "• /export → envoie toutes les fiches en .txt\n"
            "• /num <numéro> → cherche et renvoie la/les fiche(s)\n",
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
        # Dédupe
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
        """Commande /num <numero> — recherche par numéro ou 4 derniers."""
        args = context.args if hasattr(context, "args") else []
        query = " ".join(args).strip()
        if not query:
            await update.message.reply_text("Utilisation : /num <numéro> (ex: /num 0612345678 ou /num 1234)")
            return
        await self._reply_with_results(update, query)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Réponse quand l’utilisateur envoie un texte simple (numéros séparés par virgule/ligne)."""
        txt = (update.message.text or "").strip()
        queries = [t for t in re.split(r"[\n,;]", txt) if t.strip()]
        for q in queries:
            await self._reply_with_results(update, q)

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

        # Dédupe des réponses identiques
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

def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    csv_path = os.getenv("CSV_PATH", CSV_PATH_DEFAULT)
    if not token:
        raise SystemExit("Veuillez éditer .env et mettre BOT_TOKEN=...")
    if not os.path.exists(csv_path):
        raise SystemExit(f"Fichier CSV introuvable: {csv_path}")
    App(token, csv_path).start()

if __name__ == "__main__":
    main()
