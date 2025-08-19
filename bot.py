# -*- coding: utf-8 -*-
import os, io, re, json, csv, gzip, tempfile, shutil
from datetime import date, datetime
from typing import Dict, Any, List, Optional, Iterable, Tuple

import requests
import ijson
from dateutil import parser as dateparser
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ========= Config =========
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", "data")  # emplacement où on enregistre tout
os.makedirs(DATA_DIR, exist_ok=True)

# ========= Départements -> Régions =========
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

# ========= État filtres =========
# bics: ensemble de patterns (match sur BIC ou IBAN)
# depts: ensemble de codes "01..95", "2A", "2B"
# age_ranges: liste de tuples (min, max)
# (on garde aussi age_min/age_max pour compatibilité)
user_filters: Dict[int, Dict[str, Any]] = {}
def get_user_filters(uid: int) -> Dict[str, Any]:
    if uid not in user_filters:
        user_filters[uid] = {
            "bics": set(), "depts": set(),
            "age_ranges": [],
            "age_min": None, "age_max": None,
        }
    return user_filters[uid]

# ========= Utilitaires =========
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

def cp_to_dept(cp: str) -> Optional[str]:
    if not cp: return None
    cp = cp.strip().upper()
    if cp.startswith("2A"): return "2A"
    if cp.startswith("2B"): return "2B"
    m = re.match(r"^(\d{2})", cp)
    return m.group(1) if m else None

def cp_to_region(cp: str) -> Optional[str]:
    if not cp: return None
    if re.match(r"^97[1-6]", cp): return "DROM"
    d = cp_to_dept(cp)
    return DEPT_TO_REGION.get(d) if d else None

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

    # Département & région
    cp = remapped.get("Code Postal", "")
    dept = cp_to_dept(re.sub(r"\s+", "", cp))
    if dept: remapped["_dept"] = dept
    if not remapped.get("Région"):
        reg = cp_to_region(re.sub(r"\s+", "", cp)) if cp else None
        if reg: remapped["Région"] = reg

    # Âge
    for key in ("Date de naissance","date_naissance","dob"):
        if remapped.get(key):
            a = compute_age(remapped[key])
            if a is not None:
                remapped["_age"] = a
                break

    return remapped

FIELDS_ORDER = ["Civilité","Prénom","Nom","Date de naissance","Email","Mobile","Téléphone Fixe",
                "Adresse","Ville","Code Postal","Région","IBAN","BIC"]

def write_fiche(fp, idx: int, rec: Dict[str, Any]) -> int:
    buf = [f"FICHE {idx}", "-"*60]
    for k in FIELDS_ORDER: buf.append(f"{k}: {rec.get(k,'')}")
    buf += ["-"*60, ""]
    s = "\n".join(buf)
    fp.write(s)
    return len(s.encode("utf-8"))

# ========= Filtrage =========
def record_passes(rec: Dict[str, Any], f: Dict[str, Any]) -> bool:
    # Ages
    a = rec.get("_age")

    # Tranches (age_ranges) si présentes
    ranges: List[Tuple[int,int]] = f.get("age_ranges") or []
    if ranges:
        if a is None: return False
        if not any(lo <= a <= hi for (lo, hi) in ranges):
            return False
    else:
        mn, mx = f.get("age_min"), f.get("age_max")
        if mn is not None or mx is not None:
            if a is None: return False
            if (mn is not None and a < mn) or (mx is not None and a > mx):
                return False

    # Départements
    depts = {d.upper() for d in f.get("depts", set())}
    if depts:
        dept = str(rec.get("_dept", "")).upper()
        if dept not in depts:
            return False

    # BIC / IBAN
    bics = {b.upper() for b in f.get("bics", set())}
    if bics:
        bic_val = (rec.get("BIC", "") or "").upper()
        iban_val = (rec.get("IBAN", "") or "").upper()
        hay = bic_val + " " + iban_val
        if not any(p in hay for p in bics):
            return False

    return True

# ========= Parsing fichiers (streaming) =========
def stream_csv(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "rb") as fb:
        first_line = fb.readline()
        header = first_line.decode("utf-8", errors="ignore")
        sep = ";" if header.count(";") >= header.count(",") else ","
        rest = io.TextIOWrapper(fb, encoding="utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(header + rest.read()), delimiter=sep)
        for row in reader:
            clean = {k: v for k, v in row.items() if v is not None and str(v).strip() != ""}
            if clean: yield normalize_record(clean)

def stream_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "rb") as fb:
        for raw in fb:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line: continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict): yield normalize_record(obj)
            except Exception:
                continue

def stream_json_array(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "rb") as fb:
        for obj in ijson.items(fb, "item"):
            if isinstance(obj, dict): yield normalize_record(obj)

def detect_and_stream(path: str, filename: str) -> Iterable[Dict[str, Any]]:
    name = (filename or "").lower()

    # .gz ?
    if name.endswith(".gz"):
        # décompresse en fichier temp pour simplifier les parsers
        with gzip.open(path, "rb") as g, tempfile.NamedTemporaryFile(delete=False) as tmp:
            shutil.copyfileobj(g, tmp)
            inner = tmp.name
        try:
            base = name[:-3]
            for rec in detect_and_stream(inner, base):
                yield rec
        finally:
            try: os.remove(inner)
            except Exception: pass
        return

    if name.endswith(".csv"):
        for rec in stream_csv(path): yield rec
        return
    if name.endswith(".jsonl"):
        for rec in stream_jsonl(path): yield rec
        return
    if name.endswith(".json"):
        # On tente JSONL d'abord (si fichier mixte)
        any_line = False
        with open(path, "rb") as fb:
            for _ in fb:
                any_line = True
                break
        if any_line:
            # test rapide jsonl
            # (si pas jsonl, on passera en array)
            try:
                for rec in stream_jsonl(path): 
                    yield rec
                return
            except Exception:
                pass
        for rec in stream_json_array(path): yield rec
        return

    # Fallback texte clé:valeur
    with open(path, "rb") as fb:
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

# ========= Téléchargement gros fichiers =========
MAX_DOWNLOAD = 5 * 1024 * 1024 * 1024  # 5 Go max (sécurité)
CHUNK = 4 * 1024 * 1024                # 4 Mo
PART_LIMIT = 45 * 1024 * 1024          # ~45 Mo par fichier .txt de sortie

def download_to(path_dir: str, url: str) -> Tuple[str, str]:
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    name = url.split("?")[0].split("/")[-1] or "remote.bin"
    out_path = os.path.join(path_dir, name)
    total = 0
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(CHUNK):
            if not chunk: continue
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                f.close()
                os.remove(out_path)
                raise RuntimeError("Fichier trop volumineux (>5 Go).")
            f.write(chunk)
    return out_path, name

# ========= Sortie en parts =========
def process_stream_to_parts(stream: Iterable[Dict[str, Any]], f: Dict[str, Any], base_name: str, out_dir: str) -> List[str]:
    parts = []
    idx = 0
    part_idx = 1
    cur_size = 0
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{base_name}_fiches_part{part_idx}.txt")
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
                out_path = os.path.join(out_dir, f"{base_name}_fiches_part{part_idx}.txt")
                fp = open(out_path, "w", encoding="utf-8", newline="\n")
                parts.append(out_path)
    finally:
        fp.close()

    cleaned = []
    for p in parts:
        if os.path.getsize(p) > 0:
            cleaned.append(p)
        else:
            try: os.remove(p)
            except Exception: pass
    return cleaned

# ========= UI / Aide =========
def now_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")

def user_folder(user_id: int) -> str:
    d = os.path.join(DATA_DIR, f"{now_tag()}_{user_id}")
    os.makedirs(d, exist_ok=True)
    return d

HELP = (
    "📎 Envoie un fichier `.txt`, `.csv`, `.json/.jsonl` → je renvoie un TXT **FICHE 1, FICHE 2…**.\n\n"
    "🎯 *Filtre compact* :\n"
    "`/filtre bic:SOGE,BNPA region:93,82 age:18-25,40-60`\n"
    "Variantes : `bic=...`, `region93`, `dept01`, `age30-55`\n\n"
    "🌐 Gros fichiers : `/importurl <lien direct>` (Dropbox: mets `dl=1`).\n"
)

def cfg_table(f: Dict[str, Any]) -> str:
    ranges_txt = ", ".join([f"{a}-{b}" for a,b in (f.get('age_ranges') or [])]) or "-"
    mn = f["age_min"] if f["age_min"] is not None else "-"
    mx = f["age_max"] if f["age_max"] is not None else "-"
    depts_txt = ", ".join(sorted({d.upper() for d in f.get("depts", set())})) or "-"
    bics_txt  = ", ".join(sorted({b.upper() for b in f.get("bics", set())})) or "-"
    return (
        "📋 *Tableau de configuration*\n"
        "```\n"
        f"{'Option':<16}| Valeur\n"
        f"{'-'*35}\n"
        f"{'Tranches âge':<16}| {ranges_txt}\n"
        f"{'Age min/max':<16}| {mn} / {mx}\n"
        f"{'Départements':<16}| {depts_txt}\n"
        f"{'BIC/Banque':<16}| {bics_txt}\n"
        "```\n"
    )

# ========= Commandes =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(cfg_table(f) + HELP, parse_mode="Markdown", disable_web_page_preview=True)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    await update.message.reply_text(cfg_table(f) + HELP, parse_mode="Markdown", disable_web_page_preview=True)

# /filtre bic:SOGE,BNPA region:93,82 age:18-25,40-60
DEPT_RE  = re.compile(r'\b(2A|2B|\d{2})\b', re.IGNORECASE)
RANGE_RE = re.compile(r'(\d{1,3})\s*[-:]\s*(\d{1,3})')

def parse_filtre_args(text: str):
    bics, depts, ranges = set(), set(), []
    joined = " " + text + " "

    # BIC
    for m in re.finditer(r'\b(?:bic|banque)\s*[:=]\s*([^\s]+)', joined, re.IGNORECASE):
        bics.update(re.split(r'[,\s]+', m.group(1).strip()))
    for m in re.finditer(r'\bbic([A-Za-z0-9,]+)\b', joined, re.IGNORECASE):
        bics.update(re.split(r'[,\s]+', m.group(1).strip()))

    # Départements
    for m in re.finditer(r'\b(?:region|région|dept|departement)\s*[:=]?\s*([A-Za-z0-9, ]+)', joined, re.IGNORECASE):
        for d in DEPT_RE.findall(m.group(1)): depts.add(d.upper())
    for m in re.finditer(r'\b(?:region|région|dept)(2A|2B|\d{2})\b', joined, re.IGNORECASE):
        depts.add(m.group(1).upper())

    # Ages / Branches
    for m in re.finditer(r'\b(?:age|âge|branche)\s*[:=]\s*([0-9,\-\s]+)', joined, re.IGNORECASE):
        for r in m.group(1).split(','):
            mt = RANGE_RE.search(r)
            if mt:
                a, b = int(mt.group(1)), int(mt.group(2))
                if a <= b: ranges.append((a, b))
    for m in re.finditer(r'\b(?:age|âge|branche)(\d{1,3}\s*[-:]\s*\d{1,3})\b', joined, re.IGNORECASE):
        a, b = RANGE_RE.search(m.group(1)).groups()
        a, b = int(a), int(b)
        if a <= b: ranges.append((a, b))

    return {"bics": {x.upper() for x in bics if x}, "depts": depts, "ranges": ranges}

async def filtre_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "Utilisation : `/filtre bic:SOGE,BNPA region:93,82 age:18-25,40-60`",
            parse_mode="Markdown"
        )
        return
    parsed = parse_filtre_args(query)
    if parsed["bics"]:   f["bics"]   = set(parsed["bics"])
    if parsed["depts"]:  f["depts"]  = set(parsed["depts"])
    if parsed["ranges"]:
        f["age_ranges"] = parsed["ranges"]
        f["age_min"] = None; f["age_max"] = None

    await update.message.reply_text(cfg_table(f), parse_mode="Markdown")

# Compat min/max si tu veux encore les utiliser
async def setage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    f = get_user_filters(update.effective_user.id)
    try:
        if len(context.args) == 2:
            mn, mx = int(context.args[0]), int(context.args[1])
            if mn < 0 or mx < 0 or mn > mx: raise ValueError()
            f["age_min"], f["age_max"] = mn, mx
            f["age_ranges"] = []
        elif len(context.args) == 1:
            mn = int(context.args[0]); 
            if mn < 0: raise ValueError()
            f["age_min"], f["age_max"] = mn, None
            f["age_ranges"] = []
        else:
            await update.message.reply_text("Utilisation: /setage <min> [max]"); return
        await update.message.reply_text(cfg_table(f), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Valeurs invalides. Exemple: /setage 18 35")

# ========= Traitement & enregistrement =========
def save_bytes_to(dirpath: str, filename: str, data: bytes) -> str:
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, filename)
    with open(path, "wb") as f: f.write(data)
    return path

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Envoie un fichier .txt / .csv / .json 😉")
        return

    # si trop gros pour upload direct → conseiller importurl
    if doc.file_size and doc.file_size > 45 * 1024 * 1024:
        await update.message.reply_text("⚠️ Fichier volumineux : utilise `/importurl <lien direct>` (Dropbox/Drive).")
        return

    tgfile = await doc.get_file()
    data = await tgfile.download_as_bytes()
    fname = doc.file_name or "input.bin"

    udir = user_folder(update.effective_user.id)
    in_path = save_bytes_to(udir, fname, data)  # on enregistre le fichier d’entrée

    f = get_user_filters(update.effective_user.id)
    base = re.sub(r"\.([A-Za-z0-9]+)(\.gz)?$", "", fname)
    out_dir = os.path.join(udir, "out")
    parts = process_stream_to_parts(detect_and_stream(in_path, fname), f, base, out_dir)

    if not parts:
        await update.message.reply_text("❌ Aucune fiche après filtrage.")
        return

    for p in parts:
        with open(p, "rb") as rd:
            await update.message.reply_document(rd, caption=f"✅ {os.path.basename(p)}")

async def importurl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Utilisation : `/importurl <lien direct>`", parse_mode="Markdown")
        return
    url = context.args[0]
    udir = user_folder(update.effective_user.id)

    try:
        await update.message.reply_text("⏬ Téléchargement en cours (streaming)…")
        in_path, name = download_to(udir, url)   # le fichier téléchargé est enregistré
        f = get_user_filters(update.effective_user.id)
        base = re.sub(r"\.([A-Za-z0-9]+)(\.gz)?$", "", name)
        out_dir = os.path.join(udir, "out")
        await update.message.reply_text("🔧 Traitement… (je découpe en parties si besoin)")
        parts = process_stream_to_parts(detect_and_stream(in_path, name), f, base, out_dir)

        if not parts:
            await update.message.reply_text("❌ Aucune fiche après filtrage.")
            return

        for p in parts:
            with open(p, "rb") as rd:
                await update.message.reply_document(rd, caption=f"✅ {os.path.basename(p)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Échec : {e}")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commande inconnue. Aide: /help")

# ========= Bootstrap =========
async def _post_init(app: Application):
    # supprime un webhook résiduel (évite les erreurs 'Conflict')
    await app.bot.delete_webhook(drop_pending_updates=True)

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("filtre", filtre_cmd))
    app.add_handler(CommandHandler("setage", setage))   # optionnel
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
