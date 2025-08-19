# bot.py (version sans pandas)
# -*- coding: utf-8 -*-

import io
import json
import os
import re
import csv
from datetime import date
from typing import Dict, Any, List, Optional

from dateutil import parser as dateparser
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

DEPT_TO_REGION = {
    "01":"Auvergne-Rhône-Alpes","03":"Auvergne-Rhône-Alpes","07":"Auvergne-Rhône-Alpes","15":"Auvergne-Rhône-Alpes",
    "26":"Auvergne-Rhône-Alpes","38":"Auvergne-Rhône-Alpes","42":"Auvergne-Rhône-Alpes","43":"Auvergne-Rhône-Alpes",
    "63":"Auvergne-Rhône-Alpes","69":"Auvergne-Rhône-Alpes","73":"Auvergne-Rhône-Alpes","74":"Auvergne-Rhône-Alpes",
    "21":"Bourgogne-Franche-Comté","25":"Bourgogne-Franche-Comté","39":"Bourgogne-Franche-Comté","58":"Bourgogne-Franche-Comté",
    "70":"Bourgogne-Franche-Comté","71":"Bourgogne-Franche-Comté","89":"Bourgogne-Franche-Comté","90":"Bourgogne-Franche-Comté",
    "22":"Bretagne","29":"Bretagne","35":"Bretagne","56":"Bretagne",
    "18":"Centre-Val de Loire","28":"Centre-Val de Loire","36":"Centre-Val de Loire","37":"Centre-Val de Loire","41":"Centre-Val de Loire","45":"Centre-Val de Loire",
    "08":"Grand Est","10":"Grand Est","51":"Grand Est","52":"Grand Est","54":"Grand Est","55":"Grand Est","57":"Grand Est","67":"Grand Est","68":"Grand Est","88":"Grand Est",
    "02":"Hauts-de-France","59":"Hauts-de-France","60":"Hauts-de-France","62":"Hauts-de-France","80":"Hauts-de-France",
    "75":"Île-de-France","77":"Île-de-France","78":"Île-de-France","91":"Île-de-France","92":"Île-de-France","93":"Île-de-France","94":"Île-de-France","95":"Île-de-France",
    "14":"Normandie","27":"Normandie","50":"Normandie","61":"Normandie","76":"Normandie",
    "16":"Nouvelle-Aquitaine","17":"Nouvelle-Aquitaine","19":"Nouvelle-Aquitaine","23":"Nouvelle-Aquitaine","24":"Nouvelle-Aquitaine",
    "33":"Nouvelle-Aquitaine","40":"Nouvelle-Aquitaine","47":"Nouvelle-Aquitaine","64":"Nouvelle-Aquitaine","79":"Nouvelle-Aquitaine","86":"Nouvelle-Aquitaine","87":"Nouvelle-Aquitaine",
    "09":"Occitanie","11":"Occitanie","12":"Occitanie","30":"Occitanie","31":"Occitanie","32":"Occitanie","34":"Occitanie",
    "46":"Occitanie","48":"Occitanie","65":"Occitanie","66":"Occitanie","81":"Occitanie","82":"Occitanie",
    "44":"Pays de la Loire","49":"Pays de la Loire","53":"Pays de la Loire","72":"Pays de la Loire","85":"Pays de la Loire",
    "04":"Provence-Alpes-Côte d'Azur","05":"Provence-Alpes-Côte d'Azur","06":"Provence-Alpes-Côte d'Azur",
    "13":"Provence-Alpes-Côte d'Azur","83":"Provence-Alpes-Côte d'Azur","84":"Provence-Alpes-Côte d'Azur",
    "2A":"Corse","2B":"Corse",
}
REGIONS = sorted(set(DEPT_TO_REGION.values()) | {"DROM"})

user_filters: Dict[int, Dict[str, Any]] = {}

def get_user_filters(user_id: int) -> Dict[str, Any]:
    if user_id not in user_filters:
        user_filters[user_id] = {"age_min": None, "age_max": None, "regions": set()}
    return user_filters[user_id]

def compute_age(dob_str: str) -> Optional[int]:
    if not dob_str:
        return None
    try:
        dt = dateparser.parse(dob_str, dayfirst=True, yearfirst=False)
        if not dt: return None
        today = date.today()
        years = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
        return years if 0 <= years <= 130 else None
    except Exception:
        return None

def cp_to_region(cp: str) -> Optional[str]:
    if not cp: return None
    cp = cp.strip()
    if re.match(r"^97[1-6]", cp):  # DROM
        return "DROM"
    if cp.upper().startswith("2A") or cp.upper().startswith("2B"):
        return "Corse"
    m = re.match(r"^(\d{2})", cp)
    return DEPT_TO_REGION.get(m.group(1)) if m else None

def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {k.strip(): ("" if v is None else str(v).strip()) for k, v in rec.items()}
    aliases = {
        "civilité":"Civilité","civilite":"Civilité",
        "prenom":"Prénom","prénom":"Prénom","first_name":"Prénom","given_name":"Prénom",
        "nom":"Nom","last_name":"Nom","family_name":"Nom",
        "date_naissance":"Date de naissance","date de naissance":"Date de naissance","dob":"Date de naissance",
        "email":"Email","e-mail":"Email","mail":"Email",
        "mobile":"Mobile","portable":"Mobile","gsm":"Mobile","tel_portable":"Mobile","phone_mobile":"Mobile",
        "fixe":"Téléphone Fixe","telephone":"Téléphone Fixe","tel_fixe":"Téléphone Fixe",
        "adresse":"Adresse","address":"Adresse","adresse_postale":"Adresse",
        "ville":"Ville","city":"Ville","localité":"Ville","localite":"Ville",
        "cp":"Code Postal","code_postal":"Code Postal","postal":"Code Postal","zip":"Code Postal","zipcode":"Code Postal",
        "iban":"IBAN","bic":"BIC","swift":"BIC",
        "region":"Région","région":"Région",
    }
    remapped = {}
    for k, v in out.items():
        key = aliases.get(k.lower(), k)
        remapped[key] = v
    if not remapped.get("Région"):
        cp = remapped.get("Code Postal", "")
        reg = cp_to_region(re.sub(r"\D", "", cp)) if cp else None
        if reg: remapped["Région"] = reg
    age = None
    for key in ["Date de naissance", "date_naissance", "dob"]:
        if key in remapped and remapped[key]:
            age = compute_age(remapped[key]); break
    if age is not None:
        remapped["_age"] = age
    return remapped

def apply_filters(records: List[Dict[str, Any]], f: Dict[str, Any]) -> List[Dict[str, Any]]:
    age_min = f.get("age_min"); age_max = f.get("age_max")
    regions = {r.lower() for r in f.get("regions", set())}
    def ok(r: Dict[str, Any]) -> bool:
        if age_min is not None or age_max is not None:
            a = r.get("_age")
            if a is None or (age_min is not None and a < age_min) or (age_max is not None and a > age_max):
                return False
        if regions:
            reg = r.get("Région", "")
            if reg.lower() not in regions: return False
        return True
    return [rec for rec in records if ok(rec)]

def make_fiches_txt(records: List[Dict[str, Any]]) -> str:
    if not records: return "Aucune fiche après filtrage."
    order = ["Civilité","Prénom","Nom","Date de naissance","Email","Mobile","Téléphone Fixe",
             "Adresse","Ville","Code Postal","Région","IBAN","BIC"]
    out: List[str] = []
    for i, rec in enumerate(records, 1):
        out.append(f"FICHE {i}")
        out.append("-"*60)
        for key in order:
            out.append(f"{key}: {rec.get(key,'')}")
        out.append("-"*60); out.append("")
    return "\n".join(out).strip()

# ---------- Parsers (sans pandas) ----------
def extract_from_csv_text(text: str) -> List[Dict[str, Any]]:
    # Détecte ; ou , automatiquement
    sniffer = csv.Sniffer()
    dialect = sniffer.sniff(text.splitlines()[0]) if text else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    out = []
    for row in reader:
        clean = {k: v for k, v in row.items() if v is not None and str(v).strip() != ""}
        if clean:
            out.append(normalize_record(clean))
    return out

def extract_from_json_text(text: str) -> List[Dict[str, Any]]:
    text = text.strip()
    records: List[Dict[str, Any]] = []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    records.append(normalize_record(item))
        elif isinstance(data, dict):
            records.append(normalize_record(data))
        return records
    except json.JSONDecodeError:
        pass
    # JSON-Lines
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                records.append(normalize_record(obj))
        except json.JSONDecodeError:
            continue
    return records

def extract_from_kv_txt(text: str) -> List[Dict[str, Any]]:
    blocks = re.split(r"(?:\n\s*(?:[-=]{3,}|FICHE\s+\d+)\s*\n)|\n{2,}", text, flags=re.IGNORECASE)
    out = []
    for block in blocks:
        block = block.strip()
        if not block: continue
        rec: Dict[str, Any] = {}
        for line in block.splitlines():
            m = re.match(r"\s*([^:|]+)\s*[:|]\s*(.+)\s*$", line)
            if not m: continue
            k, v = m.group(1), m.group(2)
            rec[k.strip()] = v.strip()
        if rec:
            out.append(normalize_record(rec))
    return out

def detect_and_extract(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    name = (filename or "").lower()
    text = file_bytes.decode("utf-8", errors="ignore")
    if name.endswith(".csv"):
        return extract_from_csv_text(text)
    if name.endswith(".json") or name.endswith(".jsonl"):
        recs = extract_from_json_text(text)
        if recs: return recs
    recs = extract_from_json_text(text)
    if recs: return recs
    try:
        return extract_from_csv_text(text)
    except Exception:
        pass
    return extract_from_kv_txt(text)

# ---------- Commands ----------
HELP_TEXT = (
    "📎 Envoie un fichier `.txt`, `.csv`, `.json`/`.jsonl` → je renvoie un TXT **FICHE 1, FICHE 2…**.\n\n"
    "🔎 *Filtres* : `/setage 18 35`, `/clearage`, `/addregion Occitanie`, `/delregion Occitanie`, `/clearregions`, `/filters`"
)

def config_table_str(f: Dict[str, Any]) -> str:
    age_min = f["age_min"] if f["age_min"] is not None else "-"
    age_max = f["age_max"] if f["age_max"] is not None else "-"
    regions = ", ".join(sorted(f["regions"])) if f["regions"] else "-"
    return (
        "🔎 *Configuration actuelle*\n"
        "```\n"
        f"{'Option':<14}| Valeur\n"
        f"{'-'*27}\n"
        f"{'Âge min':<14}| {age_min}\n"
        f"{'Âge max':<14}| {age_max}\n"
        f"{'Régions':<14}| {regions}\n"
        "```\n"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(config_table_str(f) + HELP_TEXT, parse_mode="Markdown", disable_web_page_preview=True)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(config_table_str(f) + HELP_TEXT, parse_mode="Markdown", disable_web_page_preview=True)

async def set_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    try:
        if len(context.args) == 2:
            mn = int(context.args[0]); mx = int(context.args[1])
            if mn < 0 or mx < 0 or mn > mx: raise ValueError()
            f["age_min"] = mn; f["age_max"] = mx
            msg = f"✅ Filtre d’âge: {mn}–{mx}"
        elif len(context.args) == 1:
            mn = int(context.args[0]); 
            if mn < 0: raise ValueError()
            f["age_min"] = mn; f["age_max"] = None
            msg = f"✅ Filtre d’âge minimum: ≥ {mn}"
        else:
            msg = "Utilisation: /setage <min> [max]"
        await update.message.reply_text(config_table_str(f) + msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Valeurs invalides. Exemple: /setage 18 35")

async def clear_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    f["age_min"] = None; f["age_max"] = None
    await update.message.reply_text(config_table_str(f) + "🧹 Filtre d’âge supprimé.", parse_mode="Markdown")

async def add_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Utilisation: /addregion <NomDeRégion>")
        return
    reg = " ".join(context.args).strip()
    if reg.lower() not in [r.lower() for r in REGIONS]:
        await update.message.reply_text("❌ Région inconnue. Régions possibles:\n" + ", ".join(REGIONS))
        return
    f["regions"].add(reg)
    await update.message.reply_text(config_table_str(f) + f"✅ Région ajoutée: {reg}", parse_mode="Markdown")

async def del_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Utilisation: /delregion <NomDeRégion>")
        return
    reg = " ".join(context.args).strip().lower()
    before = len(f["regions"])
    f["regions"] = {r for r in f["regions"] if r.lower() != reg}
    msg = "🗑️ Région supprimée." if len(f["regions"]) < before else "ℹ️ Cette région n’était pas dans tes filtres."
    await update.message.reply_text(config_table_str(f) + msg, parse_mode="Markdown")

async def clear_regions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    f["regions"].clear()
    await update.message.reply_text(config_table_str(f) + "🧹 Filtres de région supprimés.", parse_mode="Markdown")

async def show_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(config_table_str(f), parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Envoie un fichier .txt, .csv, .json/.jsonl 😉")
        return
    tg_file = await doc.get_file()
    data = await tg_file.download_as_bytes()
    filename = doc.file_name or "input.txt"

    records = detect_and_extract(data, filename)
    if not records:
        await update.message.reply_text("❌ Aucune fiche trouvée.")
        return

    f = get_user_filters(update.effective_user.id)
    filtered = apply_filters(records, f) if (f["regions"] or f["age_min"] is not None or f["age_max"] is not None) else records

    fiches_txt = make_fiches_txt(filtered)
    out_name = re.sub(r"\.\w+$", "", filename) + "_fiches.txt"
    bio = io.BytesIO(fiches_txt.encode("utf-8")); bio.name = out_name
    await update.message.reply_document(bio, caption=f"✅ {len(filtered)} fiche(s) produite(s).")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commande inconnue. Utilise /help pour l’aide.")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("⚠️ BOT_TOKEN manquant (Environment Variables).")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setage", set_age))
    app.add_handler(CommandHandler("clearage", clear_age))
    app.add_handler(CommandHandler("addregion", add_region))
    app.add_handler(CommandHandler("delregion", del_region))
    app.add_handler(CommandHandler("clearregions", clear_regions))
    app.add_handler(CommandHandler("filters", show_filters))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot started ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
