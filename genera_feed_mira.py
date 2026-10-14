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
MAX_DESCRIZIONE = 3000      # caratteri, per contenere il peso del file

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


def descrizione_riserva(titolo, brand, mpn, categoria):
    tipo = "Motore" if categoria.lower().startswith("motori") else "Ricambio originale"
    ultima_cat = categoria.split(">")[-1].strip() if categoria else ""
    parti = [f"{tipo} {brand} – {titolo}."]
    if mpn:
        parti.append(f"Codice {mpn}.")
    if ultima_cat:
        parti.append(f"Categoria: {ultima_cat}.")
    parti.append("Fornito da Cirifalco Group, distributore ufficiale Rehlko (Kohler, Lombardini). "
                 "Verifica compatibilità tramite matricola motore e spedizioni in Italia e all'estero.")
    return " ".join(parti)


def tag(nome, valore):
    return f"<{nome}>{escape(valore)}</{nome}>" if valore else ""


def main():
    testo = scarica(FEED_URL)
    righe = list(csv.DictReader(io.StringIO(testo), delimiter="\t", quotechar='"'))

    items, scartati = [], 0
    for r in righe:
        g = lambda k: (r.get(k) or "").strip()
        pid, titolo, link = g("codice"), pulisci_testo(g("nome_prodotto")), g("link")
        prezzo = prezzo_eur(g("prezzo_prodotto_con_iva"))
        if not (pid and titolo and link and prezzo):
            scartati += 1
            continue

        categoria = g("ramo_categoria").replace(":", " > ")
        mpn = g("codice_fornitore")
        brand = ricava_brand(g("marca"), categoria, titolo)
        desc = pulisci_testo(g("descrizione_completa"))
        if len(desc) < 20:
            desc = descrizione_riserva(titolo, brand, mpn, categoria)
        desc = desc[:MAX_DESCRIZIONE]

        items.append("<item>" + "".join([
            tag("g:id", pid),
            tag("title", titolo),
            tag("description", desc),
            tag("link", link),
            tag("g:image_link", g("immagine")),
            tag("g:price", prezzo),
            tag("g:availability", disponibilita(g("giacenza"))),
            tag("g:condition", "new"),
            tag("g:brand", brand),
            tag("g:mpn", mpn),
            tag("g:product_type", categoria),
        ]) + "</item>")

    print(f"Righe lette: {len(righe)} | prodotti nel feed: {len(items)} | scartati: {scartati}")
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
