#!/usr/bin/env python3
"""
Feed motori per AMBESA.com (max 24 prodotti), titoli e descrizioni EN + FR, prezzi in USD.

Fonti Liberty:
  - feed id=4 (merchant_motori): solo motori disponibili a stock (Liberty esclude i non disponibili)
  - feed id=3 (feed_completo_miraAI): tutti i motori, per completare fino a 24 con quelli su ordinazione
Output: feed_ambesa_motori.xml
"""

import csv
import html
import io
import re
import sys
import urllib.request
from xml.sax.saxutils import escape

# ---------------- PARAMETRI MODIFICABILI ----------------
CAMBIO_EUR_USD = 1.15        # cambio fisso EUR -> USD
IVA = 1.22                   # i prezzi Liberty sono IVA inclusa: per l'export si usa il netto
MAX_PRODOTTI = 24            # limite Ambesa
QTA_A_STOCK = 1              # quantità indicata per i motori a stock
CATEGORIA = "Industrial Machinery///Power Transmission///Motors"   # categoria Ambesa (separatore ///)
# --------------------------------------------------------

URL_STOCK = "http://www.ricambiemotori.it/tools/feed.php?id=4"
URL_TUTTI = "http://www.ricambiemotori.it/tools/feed.php?id=3"
OUTPUT = "feed_ambesa_motori.xml"

csv.field_size_limit(10_000_000)

# Frasi italiane dei titoli -> (inglese, francese). L'ordine conta: prima le frasi più lunghe.
FRASI = [
    (r"con albero conico (?:da )?(\d+) ?mm", r"with \1 mm tapered shaft", r"avec arbre conique \1 mm"),
    (r"albero conico (?:da )?(\d+) ?mm", r"\1 mm tapered shaft", r"arbre conique \1 mm"),
    (r"con albero cilindrico (?:da )?([\d,/ ]+) ?mm", r"with \1 mm straight shaft", r"avec arbre cylindrique \1 mm"),
    (r"albero cilindrico (?:da )?([\d,/ ]+) ?mm", r"\1 mm straight shaft", r"arbre cylindrique \1 mm"),
    (r"con avviamento elettrico", "with electric start", "avec démarrage électrique"),
    (r"avviamento elettrico", "electric start", "démarrage électrique"),
    (r"con riduttore", "with reduction gearbox", "avec réducteur"),
    (r"riduttore", "reduction gearbox", "réducteur"),
    (r"versione antincendio", "fire pump version", "version incendie"),
    (r"con filtro", "with filter", "avec filtre"),
    (r"industriale", "industrial", "industriel"),
    (r"per", "for", "pour"),
    (r"cono", "taper", "cône"),
    (r"benzina", "", ""),
    (r"diesel", "", ""),
    (r"motore", "", ""),
]


def scarica_tsv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (feed-ambesa)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            testo = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return list(csv.DictReader(io.StringIO(testo), delimiter="\t", quotechar='"'))


def pulisci(t):
    t = html.unescape(t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def prezzo_usd(v):
    try:
        lordo = float(str(v).replace("EUR", "").replace(",", ".").strip())
    except ValueError:
        return None
    if lordo <= 0:
        return None
    return round(lordo / IVA * CAMBIO_EUR_USD)


def alimentazione(titolo):
    t = titolo.lower()
    if "diesel" in t or re.search(r"\b(kd|ldw|kdw|kdi|ksd|\d+ld)\s?-?\d", t):
        return "diesel"
    return "petrol"


def traduci(titolo):
    base = re.sub(r"^[A-Z]\s*-\s*", "", titolo)              # toglie il prefisso "A - "
    base = re.sub(r"(?i)^motore\s+", "", base)
    base = re.sub(r"(?i)^rehlko\s+", "", base)
    base = re.sub(r"(?i)^engine\s+", "", base)
    en, fr = base, base
    for it, e, f in FRASI:
        en = re.sub(rf"(?i)\b{it}\b", e, en)
        fr = re.sub(rf"(?i)\b{it}\b", f, fr)
    en = re.sub(r"\s+", " ", en).strip(" -")
    fr = re.sub(r"\s+", " ", fr).strip(" -")
    return en, fr


PAROLE_BASE = ("engine engines motor motors moteur moteurs rehlko kohler lombardini "
               "original genuine industrial industriel")
PAROLE_DIESEL = "diesel gasoil gazole diesel-engine generator generators genset groupe electrogene pump pompe"
PAROLE_BENZINA = "petrol gasoline gas essence benzine small-engine generator lawn mower tondeuse pump pompe"


def parole_ricerca(titolo, codice, fuel):
    t = titolo.upper()
    modelli = []
    for m in re.findall(r"\b(KDW|LDW|KDI|KSD|KD|LD|CH|CV|XT|ECH|HD)\s?-?(\d{2,4})(?:\s?-?(\d{2,4}))?", t):
        sig, n1, n2 = m
        base = [f"{sig}{n1}", f"{sig} {n1}", f"{sig}-{n1}"]
        if n2:
            base += [f"{sig}{n1}-{n2}", f"{sig}{n1} {n2}", f"{sig}{n1}{n2}"]
        if sig in ("KDW", "LDW"):
            alt = "LDW" if sig == "KDW" else "KDW"
            base += [f"{alt}{n1}", f"{alt} {n1}"]
        modelli += base
    for pre, num in re.findall(r"\b(\d{1,2})\s?LD\s?-?(\d{3})", t):     # Lombardini 3LD510, 15LD 350
        modelli += [f"{pre}LD{num}", f"{pre}LD {num}", f"{pre}LD-{num}"]
    # le sigle restano intere (anche con lo spazio): solo le liste di parole generiche vanno spezzate
    parole = PAROLE_BASE.split() + (PAROLE_DIESEL if fuel == "diesel" else PAROLE_BENZINA).split() + modelli
    if codice:
        parole += [codice, codice.replace("-", ""), codice.replace(" ", "")]
    visti, out = set(), []
    for p in parole:
        k = p.lower()
        if k not in visti:
            visti.add(k)
            out.append(p)
    return ", ".join(out)


def costruisci(r, a_stock):
    titolo = pulisci(r.get("title") or r.get("nome_prodotto"))
    codice = (r.get("mpn") or r.get("codice_fornitore") or "").strip()
    pid = (r.get("id") or r.get("codice") or "").strip()
    prezzo = prezzo_usd(r.get("price") or r.get("prezzo_prodotto_con_iva"))
    immagine = (r.get("image_link") or r.get("immagine") or "").strip()
    if not (pid and titolo and prezzo):
        return None

    fuel = alimentazione(titolo)
    en, fr = traduci(titolo)
    fuel_en = "Diesel engine" if fuel == "diesel" else "Petrol engine"
    fuel_fr = "Moteur diesel" if fuel == "diesel" else "Moteur essence"
    rif = f" – {codice}" if codice else ""
    nome = f"{fuel_en} Rehlko {en}{rif} | {fuel_fr} Rehlko {fr}"[:250]

    disp_en = "In stock, ready to ship." if a_stock else "Available on order – contact us for lead time."
    disp_fr = "En stock, prêt à expédier." if a_stock else "Disponible sur commande – contactez-nous pour le délai."
    descr = (
        f"<p><b>EN</b> – Original Rehlko (Kohler / Lombardini) {fuel_en.lower()} {en}. "
        f"Part number: {codice}. {disp_en} Supplied by Cirifalco Group, official Rehlko distributor in Italy "
        f"since 1980: technical support, engine configuration for OEMs and worldwide shipping.</p>"
        f"<p><b>FR</b> – {fuel_fr} d'origine Rehlko (Kohler / Lombardini) {fr}. "
        f"Référence : {codice}. {disp_fr} Fourni par Cirifalco Group, distributeur officiel Rehlko en Italie "
        f"depuis 1980 : support technique, configuration moteur pour OEM et expédition dans le monde entier.</p>"
    )
    breve = f"{fuel_en} Rehlko {en} – {fuel_fr} Rehlko {fr}"

    campi = {
        "product_code": f"CIR-{pid}",
        "category": CATEGORIA,
        "name": nome,
        "price": str(prezzo),
        "quantity": str(QTA_A_STOCK if a_stock else 0),
        "short_description": breve,
        "description": descr,
        "image_url": immagine,
        "search_words": parole_ricerca(titolo, codice, fuel),
        "brand": "Rehlko",
        "part_number": codice,
        "fuel": fuel,
        "availability": "in_stock" if a_stock else "on_order",
    }
    xml = "<product>" + "".join(f"<{k}>{escape(v)}</{k}>" for k, v in campi.items() if v) + "</product>"
    return fuel, xml


def main():
    stock = scarica_tsv(URL_STOCK)
    tutti = [r for r in scarica_tsv(URL_TUTTI)
             if (r.get("ramo_categoria") or "").lower().startswith("motori")]

    ids_stock = set()
    scelti_stock = []
    for r in stock:
        p = costruisci(r, True)
        if p:
            scelti_stock.append(p)
            ids_stock.add((r.get("id") or "").strip())
    scelti_stock.sort(key=lambda p: 0 if p[0] == "diesel" else 1)       # diesel davanti

    su_ordine = []
    for r in tutti:
        if (r.get("codice") or "").strip() in ids_stock:
            continue
        p = costruisci(r, False)
        if p:
            su_ordine.append(p)
    su_ordine.sort(key=lambda p: 0 if p[0] == "diesel" else 1)

    finali = (scelti_stock + su_ordine)[:MAX_PRODOTTI]
    print(f"A stock: {len(scelti_stock)} | su ordinazione disponibili: {len(su_ordine)} | nel feed: {len(finali)} "
          f"(diesel: {sum(p[0] == 'diesel' for p in finali)}, benzina: {sum(p[0] == 'petrol' for p in finali)})")
    if not finali:
        sys.exit("ERRORE: nessun motore trovato, feed non aggiornato.")

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<products>\n'
           + "\n".join(p[1] for p in finali) + "\n</products>\n")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"Scritto {OUTPUT}")


if __name__ == "__main__":
    main()
