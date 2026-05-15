#!/usr/bin/env python3
"""Diagnose the specific stuck files reported by user."""
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from sqlalchemy import text

# Files reported as stuck by user
STUCK_FILES = [
    "CSI Matforce template.Finance.Aout2013.ppt",
    "NORMES_IAS_IFRS_2008[1].pdf",
    "Recherche écart CA.xls",
    "etatdereponses2012.pdf",
    "Doctrine fiscale 2012.pdf",
    "Doctrine fiscale 2010.pdf",
    "circulaire_tva_ndeg_153_du_11.05[1] suspension tva.pdf",
    "cgi2013[1].pdf",
    "ANALYSE CA ET TVA 2012.xls",
    "Liasse Fiscale GUINEE 2012.xlsx",
    "FACT N°F10410412120058 GUINEE.docx",
    "Balance 2012 excel.xls",
    "Budget Filiales 2014 - NOTES.xlsx",
    "Template MatRégions.xls",
    "SITUATION DE LA FACTURATION 071113 - Fichier Khadija.xlsx",
    "Rattrapage Facturation PDG.xlsx",
    "liste des factures validées.xlsx",
    "FACTURES 2012.xlsx",
    "Facturation en chantier.xlsx",
    "bl en suspens.xlsx",
    "RAPPROCHEMENTS BANKS 2013 bis (2).xlsx",
    "etat de stock modele Filiales.xls",
    "Flash clients 30MAR13.xls",
]

db = SessionLocal()
try:
    print("=== Looking for specific stuck files ===\n")
    found = 0
    missing = 0
    stuck = 0

    for filename in STUCK_FILES:
        # Search by original_filename (exact or LIKE for brackets/spaces)
        rows = db.execute(text("""
            SELECT id::text as doc_id, original_filename, filename, status, pipeline_stage,
                   pipeline_error, created_at, size, mime_type
            FROM sowknow.documents
            WHERE original_filename = :name OR filename = :name
               OR original_filename ILIKE '%' || :name || '%'
            ORDER BY created_at DESC
            LIMIT 5
        """), {"name": filename})

        docs = list(rows.mappings())
        if docs:
            for r in docs:
                found += 1
                is_stuck = r['status'] in ('error', 'pending', 'processing')
                if is_stuck:
                    stuck += 1
                print(f"  {'[STUCK]' if is_stuck else '[OK]   '} {r['status']:12} | {r['original_filename'][:55]:55} | stage={r['pipeline_stage'] or 'N/A':12} | err={r['pipeline_error'] or 'N/A'}")
        else:
            missing += 1
            print(f"  [MISSING] {filename[:55]:55}")

    print(f"\n=== Summary ===")
    print(f"Total requested:   {len(STUCK_FILES)}")
    print(f"Found in DB:       {found}")
    print(f"Missing from DB:   {missing}")
    print(f"Currently stuck:   {stuck}")

    # Also show overall stuck document stats
    print(f"\n=== Overall stuck document stats ===")
    rows = db.execute(text("""
        SELECT status, COUNT(*) as cnt
        FROM sowknow.documents
        WHERE status IN ('error', 'pending', 'processing')
        GROUP BY status
        ORDER BY status
    """))
    for r in rows.mappings():
        print(f"  {r['status']}: {r['cnt']}")

finally:
    db.close()
