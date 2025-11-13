"""
Exemple de bot pédagogique : lecture d’un fichier "Cle : Valeur" et recherche de numéros FR
⚠️  Utiliser uniquement avec des données fictives
"""
import csv, os, re
from typing import Optional, Dict, List
import phonenumbers

CLEAN_RE = re.compile(r"[^0-9+]")
FR_REGION = "FR"
KV_RE = re.compile(r"^\s*([^:]+)\s*:\s*(.*)$")

def normalize_fr(raw: str) -> Optional[str]:
    """Normalise un numéro français en 0XXXXXXXXX"""
    if not raw:
        return None
    s = CLEAN_RE.sub("", raw).strip()
    if not s:
        return None
    if s.startswith("0033"):
        s = "+" + s[2:]

    variants = [s]
    if s.startswith("33") and not s.startswith("+"):
        variants.append("+" + s)
    if len(s) == 9 and s[0] in "679":
        variants.append("0" + s)
        variants.append("+33" + s)
    if len(s) == 10 and not s.startswith("0"):
        variants.append("0" + s)

    for a in variants:
        try:
            num = phonenumbers.parse(a, None if a.startswith("+") else FR_REGION)
            if not phonenumbers.is_valid_number(num):
                continue
            national = phonenumbers.format_number(
                num, phonenumbers.PhoneNumberFormat.NATIONAL
            )
            national = CLEAN_RE.sub("", national)
            if national and not national.startswith("0") and num.country_code == 33:
                national = "0" + national
            return national
        except Exception:
            continue
    return None

def parse_txt_to_csv(txt_path: str, csv_path: str):
    """Convertit un fichier Cle:Valeur en CSV"""
    rows, cols, current = [], set(), {}
    with open(txt_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("-") and len(line) > 5:
                if current:
                    rows.append(current)
                    cols.update(current.keys())
                    current = {}
                continue
            m = KV_RE.match(line)
            if m:
                k, v = m.groups()
                current[k.strip()] = v.strip()
        if current:
            rows.append(current)
            cols.update(current.keys())

    if not rows:
        print("Aucune fiche détectée")
        return

    cols = sorted(cols)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} fiches converties -> {csv_path}")

def load_index(csv_path: str) -> Dict[str, List[Dict[str, str]]]:
    """Construit un index numéro -> fiches"""
    idx = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for k, v in row.items():
                if "tel" in k.lower() or "mobile" in k.lower():
                    n = normalize_fr(v)
                    if n:
                        idx.setdefault(n, []).append(row)
    print(f"{len(idx)} numéros indexés.")
    return idx

def search(idx: Dict[str, List[Dict[str, str]]], q: str):
    """Recherche simple par numéro"""
    qn = normalize_fr(q)
    if qn and qn in idx:
        return idx[qn]
    last4 = re.sub(r"\D", "", q)[-4:]
    if len(last4) == 4:
        return [r for n,lst in idx.items() if n.endswith(last4) for r in lst]
    return []

if __name__ == "__main__":
    # Exemple d’utilisation avec un fichier fictif
    if not os.path.exists("fiches.txt"):
        with open("fiches.txt", "w", encoding="utf-8") as f:
            f.write("""Nom : Dupont
Prenom : Jean
Telephone mobile : +33 6 12 34 56 78
Ville : Paris
----------------------------------------
Nom : Martin
Prenom : Paul
Telephone mobile : 0611223344
Ville : Lyon
""")
    parse_txt_to_csv("fiches.txt", "fiches.csv")
    index = load_index("fiches.csv")
    q = input("Numéro à rechercher : ")
    res = search(index, q)
    if not res:
        print("Aucune fiche trouvée.")
    else:
        for i, r in enumerate(res, 1):
            print(f"\n--- Fiche {i} ---")
            for k, v in r.items():
                if v:
                    print(f"{k}: {v}")
