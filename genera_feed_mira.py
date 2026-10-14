#!/usr/bin/env python3
"""
Converte il feed Liberty "feed_completo_miraAI" (TSV) nel formato XML
Google Merchant letto da Smartsupp Mira.

Sorgente:  http://www.ricambiemotori.it/tools/feed.php?id=3
Output:    feed_mira_completo.xml
"""

import csv
import html
import io
import re
import sys
import urllib.request
from xml.sax.saxutils import escape

FEED_URL = "http://www.ricambiemotori.it/tools/feed.php?id=3"
OUTPUT = "feed_mira_completo.xml"
MIN_PRODOTTI = 500          # sotto questa soglia il feed è considerato rotto e NON viene sovrascritto
MAX_DESCRIZIONE = 300       # caratteri, per contenere il peso del file
MAX_MB = 16.0               # peso massimo del file: oltre, Smartsupp va in timeout

csv.field_size_limit(10_000_000)


def scarica(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (feed-mira)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def pulisci_testo(t):
    if not t:
        return ""
    t = html.unescape(t)
    t = re.sub(r"<[^>]+>", " ", t)                      # tag HTML
    t = re.sub(r"(?:(?<=\s)|^)\?+(?=\s)", " ", t)       # "?" isolati = emoji non codificate
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)  # caratteri non validi in XML
    t = re.sub(r"\s+", " ", t).strip()
    return t


def prezzo_eur(v):
    try:
        p = float(str(v).replace(",", ".").strip())
    except ValueError:
        return None
    return f"{p:.2f} EUR" if p > 0 else None


def ricava_brand(marca, categoria, titolo):
    if marca:
        return marca
    c, t = categoria.upper(), titolo.upper()
    if c.startswith("RICAMBI LOMBARDINI"):
        return "Lombardini"
    if c.startswith("RICAMBI KOHLER"):
        return "Kohler"
    if "LOMBARDINI" in t:
        return "Lombardini"
    if "KOHLER" in t:
        return "Kohler"
    return "Rehlko"


def disponibilita(giacenza):
    try:
        return "in_stock" if float(str(giacenza).replace(",", ".")) > 0 else "out_of_stock"
    except ValueError:
        return "out_of_stock"


def varianti_codice(mpn):
    """Altre scritture dello stesso codice, per la ricerca di Mira."""
    c = mpn.replace(" ", "")
    base = re.sub(r"-S$", "", c)
    v = {c, c.replace("-", ""), base}
    m = re.fullmatch(r"ED00(\d{8})", base)          # Lombardini: ED0047400240-S
    if m:
        d = m.group(1)
        v.add(d)                                   # 47400240
        if d.endswith("0"):
            v.add(f"{d[:4]}.{d[4:7]}")             # 4740.024 (codice Lombardini storico)
            v.add(d[:7])                           # 4740024
    v.discard(mpn)
    v.discard("")
    return sorted(v)


# Termini inglesi dei ricambi -> nome italiano (per le ricerche dei clienti in italiano)
TERMINI_IT = [
    ("CYLINDER HEAD GASKET", "guarnizione testata"), ("HEAD GASKET", "guarnizione testata"),
    ("OIL SEAL", "paraolio"), ("O-RING", "o-ring guarnizione"), ("GASKET", "guarnizione"),
    ("SEAL", "tenuta paraolio"), ("RING SET", "fasce elastiche"), ("PISTON RING", "fasce elastiche"),
    ("PISTON", "pistone"), ("LINER", "canna cilindro"), ("CYLINDER HEAD", "testata"),
    ("CYLINDER", "cilindro"), ("CONNECTING ROD", "biella"), ("CRANKSHAFT", "albero motore"),
    ("CAMSHAFT", "albero a camme"), ("FLYWHEEL", "volano"), ("BEARING", "cuscinetto bronzina"),
    ("BUSHING", "boccola"), ("TAPPET", "punteria"), ("PUSH ROD", "asta punteria"),
    ("PUSHROD", "asta punteria"), ("ROCKER ARM", "bilanciere"), ("ROCKER COVER", "coperchio bilancieri"),
    ("VALVE GUIDE", "guida valvola"), ("VALVE SPRING", "molla valvola"), ("VALVE", "valvola"),
    ("OIL FILTER", "filtro olio"), ("FUEL FILTER", "filtro gasolio carburante"),
    ("AIR FILTER", "filtro aria"), ("FILTER CARTRIDGE", "cartuccia filtro"), ("FILTER", "filtro"),
    ("FUEL PUMP", "pompa carburante"), ("INJECTION PUMP", "pompa iniezione"),
    ("OIL PUMP", "pompa olio"), ("WATER PUMP", "pompa acqua"), ("INJECTOR", "iniettore"),
    ("NOZZLE", "polverizzatore ugello"), ("GLOW PLUG", "candeletta"), ("SPARK PLUG", "candela"),
    ("RECOIL STARTER", "avviamento a strappo"), ("STARTER MOTOR", "motorino avviamento"),
    ("STARTER", "motorino avviamento"), ("ALTERNATOR", "alternatore"), ("REGULATOR", "regolatore"),
    ("IGNITION MODULE", "modulo accensione bobina"), ("IGNITION COIL", "bobina accensione"),
    ("SOLENOID", "solenoide elettrovalvola"), ("SENSOR", "sensore"), ("SWITCH", "interruttore pressostato"),
    ("THERMOSTAT", "termostato"), ("RADIATOR", "radiatore"), ("FAN BELT", "cinghia ventola"),
    ("BELT", "cinghia"), ("FAN", "ventola"), ("PULLEY", "puleggia"), ("MUFFLER", "marmitta silenziatore"),
    ("EXHAUST", "scarico"), ("MANIFOLD", "collettore"), ("CARBURETOR", "carburatore"),
    ("GOVERNOR", "regolatore di giri"), ("THROTTLE", "acceleratore"), ("TANK", "serbatoio"),
    ("CAP", "tappo"), ("DIPSTICK", "astina olio"), ("COVER", "coperchio"), ("HOUSING", "carter"),
    ("PLATE", "piastra"), ("BRACKET", "staffa"), ("SPRING", "molla"), ("SCREW", "vite"),
    ("BOLT", "vite bullone"), ("NUT", "dado"), ("WASHER", "rondella"), ("STUD", "prigioniero"),
    ("PIN", "spina perno"), ("KEY", "chiavetta"), ("CLAMP", "fascetta"), ("HOSE", "tubo manicotto"),
    ("PIPE", "tubo"), ("TUBE", "tubo"), ("LEVER", "leva"), ("GEAR", "ingranaggio"),
    ("SHAFT", "albero"), ("BREATHER", "sfiato"), ("HARNESS", "cablaggio"), ("WIRE", "cavo"),
    ("KIT", "kit"),
]


def nomi_italiani(titolo):
    t, trovati = " " + titolo.upper() + " ", []
    for en, it in TERMINI_IT:
        if re.search(r"(?<![A-Z])" + re.escape(en) + r"(?![A-Z])", t):
            if it not in trovati:
                trovati.append(it)
            t = t.replace(en, " ")          # evita doppioni (es. OIL FILTER e FILTER)
    return [x for x in trovati if x != "kit"] or []


def modelli_motore(*testi):
    """Trova i modelli motore e restituisce le varianti di scrittura."""
    testo = " ".join(testi).upper()
    out = []
    def add(x):
        if x not in out:
            out.append(x)
    for sig, num in re.findall(r"\b(LDW|KDW|LGW)\s?-?(\d{3,4})", testo):
        for s2 in ({"LDW", "KDW"} if sig in ("LDW", "KDW") else {sig}):
            add(f"{s2}{num}"); add(f"{s2} {num}")
    for pre, num in re.findall(r"\b(\d{1,2})\s?LD\s?(\d{3})", testo):
        add(f"{pre}LD{num}"); add(f"{pre}LD {num}")
    for pre, num in re.findall(r"\bKD\s?(\d{2})\s(\d{3})", testo):
        add(f"KD{pre} {num}"); add(f"KD{pre}-{num}")
    for sig, num in re.findall(r"\b(CH|CV|KDI|KSD|ECH|CS|SH)\s?-?(\d{3,4})", testo):
        add(f"{sig}{num}"); add(f"{sig} {num}")
    return out[:10]


def descrizione_riserva(titolo, brand, categoria, motore):
    tipo = "Motore" if motore else "Ricambio originale"
    ultima_cat = categoria.split(">")[-1].strip() if categoria else ""
    testo = f"{tipo} {brand} {titolo}."
    if ultima_cat:
        testo += f" Categoria: {ultima_cat}."
    return testo


def tag(nome, valore):
    return f"<{nome}>{escape(valore)}</{nome}>" if valore else ""


def main():
    testo = scarica(FEED_URL)
    righe = list(csv.DictReader(io.StringIO(testo), delimiter="\t", quotechar='"'))

    candidati, scartati = [], 0
    for r in righe:
        g = lambda k: (r.get(k) or "").strip()
        pid, titolo, link = g("codice"), pulisci_testo(g("nome_prodotto")), g("link").split("?")[0]
        prezzo = prezzo_eur(g("prezzo_prodotto_con_iva"))
        if not (pid and titolo and link and prezzo):
            scartati += 1
            continue

        categoria = g("ramo_categoria").replace(":", " > ")
        motore = categoria.lower().startswith("motori")
        mpn = g("codice_fornitore")
        brand = ricava_brand(g("marca"), categoria, titolo)
        disp = disponibilita(g("giacenza"))
        desc_vera = pulisci_testo(g("descrizione_completa"))
        ha_desc = len(desc_vera) >= 20
        corpo = desc_vera if ha_desc else descrizione_riserva(titolo, brand, categoria, motore)

        intest = ""
        if mpn:
            var = varianti_codice(mpn)
            intest = f"Codice: {mpn}" + (f" (anche scritto {', '.join(var)})" if var else "") + ". "
        it = [] if motore else nomi_italiani(titolo)
        if it:
            intest += f"Nome: {', '.join(it)}. "
        mod = modelli_motore(titolo, desc_vera, categoria)
        if mod:
            intest += f"Sigle motore citate: {', '.join(mod)}. "
        desc = (intest + corpo)[:MAX_DESCRIZIONE]
        titolo_it = f"{titolo} ({it[0]})" if it else titolo
        titolo_feed = titolo_it if (motore or not mpn) else f"{mpn} – {titolo_it}"

        # priorità: 0 motori, 1 a stock con descrizione, 2 a stock, 3 con descrizione, 4 resto
        if motore:
            prio = 0
        elif disp == "in_stock":
            prio = 1 if ha_desc else 2
        else:
            prio = 3 if ha_desc else 4

        item = "<item>" + "".join([
            tag("g:id", pid),
            tag("g:title", titolo_feed),
            tag("g:description", desc),
            tag("g:link", link),
            tag("g:image_link", g("immagine")),
            tag("g:price", prezzo),
            tag("g:availability", disp),
            tag("g:condition", "new"),
            tag("g:brand", brand),
            tag("g:mpn", mpn),
        ]) + "</item>"
        candidati.append((prio, item))

    candidati.sort(key=lambda x: x[0])
    budget = int(MAX_MB * 1_000_000) - 2000
    items, peso, per_prio = [], 0, [0] * 5
    for prio, item in candidati:
        b = len(item.encode("utf-8")) + 1
        if peso + b > budget:
            break
        items.append(item)
        peso += b
        per_prio[prio] += 1

    print(f"Righe lette: {len(righe)} | validi: {len(candidati)} | scartati: {scartati} | nel feed: {len(items)}")
    print(f"Nel feed -> motori: {per_prio[0]} | a stock con descrizione: {per_prio[1]} | a stock: {per_prio[2]} "
          f"| non a stock con descrizione: {per_prio[3]} | altri: {per_prio[4]}")
    if len(items) < MIN_PRODOTTI:
        sys.exit(f"ERRORE: solo {len(items)} prodotti, feed non aggiornato per sicurezza.")

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>'
           "<title>Cirifalco Group – motori e ricambi</title>"
           "<link>https://www.ricambiemotori.it</link>"
           "<description>Motori Rehlko Kohler Lombardini e ricambi originali</description>\n"
           + "\n".join(items) + "\n</channel></rss>\n")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"Scritto {OUTPUT} ({len(xml.encode('utf-8')) / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    main()
