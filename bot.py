# -*- coding: utf-8 -*-
import os, io, re, json, csv, gzip, tempfile, shutil
from datetime import date
from typing import Dict, Any, List, Optional, Iterable

import requests
import ijson
from dateutil import parser as dateparser
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ===== Départements -> Régions =====
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
    "33":"Nouvelle-Aquitaine","40":"Nouvelle-Aquitaine","47":"Nouvelle-Aquitaine","64":"Nouvelle-Aquitaine",
    "79":"Nouvelle-Aquitaine","86":"Nouvelle-Aquitaine","87":"Nouvelle-Aquitaine",
    "09":"Occitanie","11":"Occitanie","12":"Occitanie","30":"Occitanie","31":"Occitanie","32":"Occitanie","34":"Occitanie",
    "46":"Occitanie","48":"Occitanie","65":"Occitanie","66":"Occitanie","81":"Occitanie","82":"Occitanie",
    "44":"Pays de la Loire","49":"Pays de la Loire","53":"Pays de la Loire","72":"Pays de la Loire","85":"Pays de la Loire",
    "04":"Provence-Alpes-Côte d'Azur","05":"Provence-Alpes-Côte d'Azur","06":"Provence-Alpes-Côte d'Azur",
    "13":"Provence-Alpes-Côte d'Azur","83":"Provence-Alpes-Côte d'Azur","84":"Provence-Alpes-Côte d'Azur",
    "2A":"Corse","2B":"Corse",
}
REGIONS = sorted(set(DEPT_TO_REGION.values()) | {"DROM"})

# ===== État filtres =====
user_filters: Dict[int, Dict[str, Any]] = {}
def get_user_filters(uid: int):
    if uid not in user_filters:
        user_filters[uid] = {"age_min": None, "age_max": None, "regions": set()}
    return user_filters[uid]

# ===== Utilitaires =====
def compute_age(dob_str: str) -> Optional[int]:
    if not dob_str: return None
    try:
        dt = dateparser.parse(dob_str, dayfirst=True, yearfirst=False)
        if not dt: return None
        today = date.today()
        age = today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
        return age if 0 <= age <= 130 else None
    except Exception:
        return None

def cp_to_region(cp: str) -> Optional[str]:
    if not cp: return None
    cp = cp.strip()
    if re.match(r"^97[1-6]", cp): return "DROM"
    if cp.upper().startswith("2A") or cp.upper().startswith("2B"): return "Corse"
    m = re.match(r"^(\d{2})", cp)
    return DEPT_TO_REGION.get(m.group(1)) if m else None

def normalize_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {k.strip(): ("" if v is None else str(v).strip()) for k, v in rec.items()}
    alias = {
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
        remapped[alias.get(k.lower(), k)] = v
    if not remapped.get("Région"):
        cp = remapped.get("Code Postal", "")
        reg = cp_to_region(re.sub(r"\D", "", cp)) if cp else None
        if reg: remapped["Région"] = reg
    for key in ("Date de naissance","date_naissance","dob"):
        if remapped.get(key):
            a = compute_age(remapped[key]); 
            if a is not None: remapped["_age"] = a; break
    return remapped

def record_passes(rec: Dict[str, Any], f: Dict[str, Any]) -> bool:
    mn, mx = f.get("age_min"), f.get("age_max")
    rset = {r.lower() for r in f.get("regions", set())}
    if mn is not None or mx is not None:
        a = rec.get("_age")
        if a is None or (mn is not None and a < mn) or (mx is not None and a > mx):
            return False
    if rset:
        reg = rec.get("Région", "")
        if reg.lower() not in rset: return False
    return True

# ===== Fiches =====
FIELDS_ORDER = ["Civilité","Prénom","Nom","Date de naissance","Email","Mobile","Téléphone Fixe",
                "Adresse","Ville","Code Postal","Région","IBAN","BIC"]

def write_fiche(fp, idx: int, rec: Dict[str, Any]) -> int:
    buf = [f"FICHE {idx}", "-"*60]
    for k in FIELDS_ORDER: buf.append(f"{k}: {rec.get(k,'')}")
    buf += ["-"*60, ""]
    s = "\n".join(buf)
    fp.write(s)
    return len(s.encode("utf-8"))

# ===== Parsers streaming =====
def stream_csv(fb) -> Iterable[Dict[str, Any]]:
    # fb: binary file-like
    # détecte séparateur sur la première ligne texte
    first_line = fb.readline()
    try:
        header = first_line.decode("utf-8", errors="ignore")
    except Exception:
        header = first_line.decode("latin-1", errors="ignore")
    sep = ";" if header.count(";") >= header.count(",") else ","
    # recompose un flux texte (première ligne + le reste)
    rest = io.TextIOWrapper(fb, encoding="utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(header + rest.read()), delimiter=sep)
    for row in reader:
        clean = {k: v for k, v in row.items() if v is not None and str(v).strip() != ""}
        if clean: yield normalize_record(clean)

def stream_jsonl(fb) -> Iterable[Dict[str, Any]]:
    for raw in fb:
        try:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line: continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield normalize_record(obj)
        except Exception:
            continue

def stream_json_array(fb) -> Iterable[Dict[str, Any]]:
    # ijson lit élément par élément d’un grand tableau JSON
    for obj in ijson.items(fb, "item"):
        if isinstance(obj, dict):
            yield normalize_record(obj)

def detect_and_stream(path: str, filename: str) -> Iterable[Dict[str, Any]]:
    name = (filename or "").lower()
    opener = open
    if name.endswith(".gz"):
        opener = lambda p, mode="rb": gzip.open(p, mode)

    if name.endswith(".csv") or name.endswith(".csv.gz"):
        with opener(path, "rb") as fb:
            for rec in stream_csv(fb): yield rec
        return

    if name.endswith(".jsonl") or name.endswith(".jsonl.gz"):
        with opener(path, "rb") as fb:
            for rec in stream_jsonl(fb): yield rec
        return

    if name.endswith(".json") or name.endswith(".json.gz"):
        with opener(path, "rb") as fb:
            # on essaie d'abord JSON Lines (au cas où), sinon tableau JSON
            pos = fb.tell()
            for rec in stream_jsonl(fb): yield rec
            if fb.tell() != pos:  # on a lu quelque chose -> on revient
                return
        with opener(path, "rb") as fb2:
            for rec in stream_json_array(fb2): yield rec
        return

    # fallback: essayer .txt key:value
    with opener(path, "rb") as fb:
        text = fb.read().decode("utf-8", errors="ignore")
    blocks = re.split(r"(?:\n\s*(?:[-=]{3,}|FICHE\s+\d+)\s*\n)|\n{2,}", text, flags=re.IGNORECASE)
    for block in blocks:
        block = block.strip()
        if not block: continue
        rec: Dict[str, Any] = {}
        for line in block.splitlines():
            m = re.match(r"\s*([^:|]+)\s*[:|]\s*(.+)\s*$", line)
            if m: rec[m.group(1).strip()] = m.group(2).strip()
        if rec: yield normalize_record(rec)

# ===== Téléchargement gros fichiers =====
MAX_DOWNLOAD = 5 * 1024 * 1024 * 1024  # 5 Go cap de sécurité
CHUNK = 4 * 1024 * 1024                # 4 Mo
PART_LIMIT = 45 * 1024 * 1024          # ~45 Mo par fichier de sortie (Telegram-friendly)

def download_to_temp(url: str) -> (str, str):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    # devine un nom
    name = url.split("?")[0].split("/")[-1] or "remote.bin"
    fd, path = tempfile.mkstemp(prefix="dl_", suffix="_" + name)
    total = 0
    with os.fdopen(fd, "wb") as f:
        for chunk in r.iter_content(CHUNK):
            if not chunk: continue
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                f.close()
                os.remove(path)
                raise RuntimeError("Fichier trop volumineux (cap de sécurité 5 Go).")
            f.write(chunk)
    return path, name

# ===== UI & commandes =====
HELP = (
    "📎 Envoie un fichier `.txt`, `.csv`, `.json/.jsonl` → je renvoie un TXT **FICHE 1, FICHE 2…**.\n\n"
    "🔎 *Filtres*\n"
    "• Âge : `/setage 18 35`, `/clearage`\n"
    "• Région : `/addregion Occitanie`, `/delregion Occitanie`, `/clearregions`\n"
    "• Voir : `/filters`\n\n"
    "🌐 *Gros fichiers (>1 Go)* : utilise `/importurl <lien>` (Dropbox/Drive/WeTransfer)."
)

def cfg_table(f: Dict[str, Any]) -> str:
    amin = f["age_min"] if f["age_min"] is not None else "-"
    amax = f["age_max"] if f["age_max"] is not None else "-"
    regs = ", ".join(sorted(f["regions"])) if f["regions"] else "-"
    return (
        "📋 *Tableau de configuration*\n"
        "```\n"
        f"{'Option':<14}| Valeur\n"
        f"{'-'*27}\n"
        f"{'Âge min':<14}| {amin}\n"
        f"{'Âge max':<14}| {amax}\n"
        f"{'Régions':<14}| {regs}\n"
        "```\n"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(cfg_table(f) + HELP, parse_mode="Markdown", disable_web_page_preview=True)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(cfg_table(f) + HELP, parse_mode="Markdown", disable_web_page_preview=True)

async def setage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    try:
        if len(context.args) == 2:
            mn = int(context.args[0]); mx = int(context.args[1])
            if mn < 0 or mx < 0 or mn > mx: raise ValueError()
            f["age_min"], f["age_max"] = mn, mx
            msg = f"✅ Filtre d’âge: {mn}–{mx}"
        elif len(context.args) == 1:
            mn = int(context.args[0]); 
            if mn < 0: raise ValueError()
            f["age_min"], f["age_max"] = mn, None
            msg = f"✅ Filtre d’âge minimum: ≥ {mn}"
        else:
            msg = "Utilisation: /setage <min> [max]"
        await update.message.reply_text(cfg_table(f) + msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Valeurs invalides. Exemple: /setage 18 35")

async def clearage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    f["age_min"] = None; f["age_max"] = None
    await update.message.reply_text(cfg_table(f) + "🧹 Filtre d’âge supprimé.", parse_mode="Markdown")

async def addregion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Utilisation: /addregion <NomDeRégion>\nEx: Occitanie, Île-de-France…")
        return
    reg = " ".join(context.args).strip()
    if reg.lower() not in [r.lower() for r in REGIONS]:
        await update.message.reply_text("❌ Région inconnue. Régions possibles:\n" + ", ".join(REGIONS))
        return
    f["regions"].add(reg)
    await update.message.reply_text(cfg_table(f) + f"✅ Région ajoutée: {reg}", parse_mode="Markdown")

async def delregion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    if not context.args:
        await update.message.reply_text("Utilisation: /delregion <NomDeRégion>")
        return
    target = " ".join(context.args).strip().lower()
    before = len(f["regions"])
    f["regions"] = {r for r in f["regions"] if r.lower() != target}
    msg = "🗑️ Région supprimée." if len(f["regions"]) < before else "ℹ️ Cette région n’était pas dans tes filtres."
    await update.message.reply_text(cfg_table(f) + msg, parse_mode="Markdown")

async def clearregions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    f["regions"].clear()
    await update.message.reply_text(cfg_table(f) + "🧹 Filtres de région supprimés.", parse_mode="Markdown")

async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(cfg_table(f), parse_mode="Markdown")

# ===== Traitement générique (stream -> txt en parties) =====
def process_stream_to_parts(stream: Iterable[Dict[str, Any]], f: Dict[str, Any], base_name: str) -> List[str]:
    """Retourne la liste des chemins des fichiers TXT générés (part-1, part-2, …)."""
    parts = []
    idx = 0
    part_idx = 1
    cur_size = 0
    tmpdir = tempfile.mkdtemp(prefix="fiches_")
    out_path = os.path.join(tmpdir, f"{base_name}_fiches_part{part_idx}.txt")
    fp = open(out_path, "w", encoding="utf-8", newline="\n")
    parts.append(out_path)

    try:
        for rec in stream:
            if not record_passes(rec, f): 
                continue
            idx += 1
            written = write_fiche(fp, idx, rec)
            cur_size += written
            if cur_size >= PART_LIMIT:
                fp.close()
                part_idx += 1
                cur_size = 0
                out_path = os.path.join(tmpdir, f"{base_name}_fiches_part{part_idx}.txt")
                fp = open(out_path, "w", encoding="utf-8", newline="\n")
                parts.append(out_path)
    finally:
        fp.close()
    # supprime les fichiers vides en queue
    cleaned = []
    for p in parts:
        if os.path.getsize(p) > 0:
            cleaned.append(p)
        else:
            try: os.remove(p)
            except Exception: pass
    return cleaned

# ===== Commande import par URL =====
async def importurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Utilisation : /importurl <lien http(s) direct>")
        return
    url = context.args[0]
    try:
        await update.message.reply_text("⏬ Téléchargement en cours (streaming)…")
        path, name = download_to_temp(url)
        base = re.sub(r"\.([A-Za-z0-9]+)(\.gz)?$", "", name)
        f = get_user_filters(update.effective_user.id)

        await update.message.reply_text("🔧 Traitement… (je te renvoie des fichiers en plusieurs parties si besoin)")
        parts = process_stream_to_parts(detect_and_stream(path, name), f, base)

        if not parts:
            await update.message.reply_text("❌ Aucune fiche après filtrage.")
            return

        for p in parts:
            with open(p, "rb") as rd:
                await update.message.reply_document(rd, caption=f"✅ {os.path.basename(p)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Échec : {e}")
    finally:
        # nettoyage
        try:
            if 'path' in locals() and os.path.exists(path): os.remove(path)
        except Exception:
            pass

# ===== Fichiers envoyés directement au bot (petits/moyens) =====
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Envoie un fichier .txt / .csv / .json 😉")
        return
    # Telegram limite l’upload direct des bots => si trop gros, conseiller /importurl
    if doc.file_size and doc.file_size > 45 * 1024 * 1024:
        await update.message.reply_text("⚠️ Fichier trop volumineux pour l’upload direct. Utilise `/importurl <lien>`.")
        return

    tgfile = await doc.get_file()
    data = await tgfile.download_as_bytes()
    fname = doc.file_name or "input.txt"
    base = re.sub(r"\.([A-Za-z0-9]+)(\.gz)?$", "", fname)
    f = get_user_filters(update.effective_user.id)

    # on met en flux mémoire -> fichier(s) de sortie (petits volumes)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{fname}")
    try:
        tmp.write(data); tmp.close()
        parts = process_stream_to_parts(detect_and_stream(tmp.name, fname), f, base)
        if not parts:
            await update.message.reply_text("❌ Aucune fiche trouvée après filtrage.")
            return
        for p in parts:
            with open(p, "rb") as rd:
                await update.message.reply_document(rd, caption=f"✅ {os.path.basename(p)}")
    finally:
        try: os.remove(tmp.name)
        except Exception: pass

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commande inconnue. Aide: /help")

# ===== Démarrage propre (supprime webhook, pas d’asyncio.run) =====
async def _post_init(app: Application):
    await app.bot.delete_webhook(drop_pending_updates=True)

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setage", setage))
    app.add_handler(CommandHandler("clearage", clearage))
    app.add_handler(CommandHandler("addregion", addregion))
    app.add_handler(CommandHandler("delregion", delregion))
    app.add_handler(CommandHandler("clearregions", clearregions))
    app.add_handler(CommandHandler("filters", filters_cmd))
    app.add_handler(CommandHandler("importurl", importurl))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

def main():
    if not BOT_TOKEN:
        raise RuntimeError("⚠️ BOT_TOKEN manquant.")
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).build()
    register_handlers(app)
    print("Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
