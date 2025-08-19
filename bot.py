import asyncio
import io
import json
import os
import re
from datetime import date
from typing import Dict, Any, List, Optional

import pandas as pd
from dateutil import parser as dateparser
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ========= CONFIG =========
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Ton token Telegram sera mis dans Render (Environment Variable)

# Mémoire simple des filtres par utilisateur
user_filters: Dict[int, Dict[str, Any]] = {}

def get_user_filters(user_id: int) -> Dict[str, Any]:
    if user_id not in user_filters:
        user_filters[user_id] = {"age_min": None, "age_max": None, "regions": set()}
    return user_filters[user_id]

# ====== UTILITAIRES ======
def compute_age(dob_str: str) -> Optional[int]:
    try:
        dt = dateparser.parse(dob_str, dayfirst=True)
        today = date.today()
        return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
    except Exception:
        return None

def make_fiches_txt(records: List[Dict[str, Any]]) -> str:
    lines = []
    for idx, rec in enumerate(records, start=1):
        lines.append(f"FICHE {idx}")
        lines.append("-" * 60)
        for k, v in rec.items():
            lines.append(f"{k}: {v}")
        lines.append("-" * 60)
        lines.append("")
    return "\n".join(lines).strip()

def detect_and_extract(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    content = file_bytes.decode("utf-8", errors="ignore")
    records: List[Dict[str, Any]] = []

    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
        records = df.to_dict(orient="records")
    elif filename.endswith(".json"):
        try:
            data = json.loads(content)
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                records = [data]
        except Exception:
            pass
    else:
        # TXT brut ligne par ligne "clé: valeur"
        current = {}
        for line in content.splitlines():
            if not line.strip():
                if current:
                    records.append(current)
                    current = {}
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                current[k.strip()] = v.strip()
        if current:
            records.append(current)
    return records

# ====== COMMANDES BOT ======
HELP_TEXT = (
    "👋 Bienvenue !\n\n"
    "Envoie-moi un fichier `.txt`, `.csv` ou `.json`.\n"
    "Je vais te renvoyer un fichier formaté en FICHE 1, FICHE 2, etc.\n\n"
    "🔎 Filtres disponibles:\n"
    "• Âge: `/setage 18 35` — `/clearage`\n"
    "• Voir filtres: `/filters`\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot prêt ✅\n\n" + HELP_TEXT)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def set_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    f = get_user_filters(uid)
    try:
        if len(context.args) == 2:
            f["age_min"] = int(context.args[0])
            f["age_max"] = int(context.args[1])
            await update.message.reply_text(f"✅ Filtre d’âge: {f['age_min']}–{f['age_max']}")
        else:
            await update.message.reply_text("Utilisation: /setage <min> <max>")
    except:
        await update.message.reply_text("❌ Mauvais format. Exemple: /setage 18 35")

async def clear_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    f = get_user_filters(uid)
    f["age_min"] = None
    f["age_max"] = None
    await update.message.reply_text("🧹 Filtre d’âge supprimé.")

async def show_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(f"🔎 Filtres actuels\nÂge: {f['age_min']}–{f['age_max']}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return
    file = await doc.get_file()
    file_bytes = await file.download_as_bytes()
    filename = doc.file_name or "input.txt"

    records = detect_and_extract(file_bytes, filename)
    if not records:
        await update.message.reply_text("❌ Impossible de lire ce fichier.")
        return

    fiches_txt = make_fiches_txt(records)

    out_name = filename.rsplit(".", 1)[0] + "_fiches.txt"
    bio = io.BytesIO(fiches_txt.encode("utf-8"))
    bio.name = out_name
    await update.message.reply_document(bio, caption=f"✅ {len(records)} fiches trouvées.")

def main():
    token = BOT_TOKEN
    if not token:
        raise RuntimeError("⚠️ Mets ton BOT_TOKEN dans les variables d'environnement (Render).")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setage", set_age))
    app.add_handler(CommandHandler("clearage", clear_age))
    app.add_handler(CommandHandler("filters", show_filters))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.run_polling()

if __name__ == "__main__":
    main()
