"""
Crée un fichier .aapatch unique couvrant DGS1 (GO/) et DGS2 (BB/).

Usage :
  python3 tools/create_patch.py \\
      --game-dir /home/korphos/.steam/debian-installation/steamapps/common/TGAAC \\
      --output tgaac_fr.aapatch

Fichiers de traduction :
  traductions/dgs1/sce00.json  …sce04.json   (un JSON par arc, clé = nom court GMD)
  traductions/dgs2/sce00_c000.json  …         (un JSON par chapitre, même format)

Prérequis : les backups .arc.bak doivent exister (créés par extract_translations_dgs1.py
pour DGS1 ; créés automatiquement à la première génération pour DGS2).
"""

import sys
import re
import json
import shutil
import tempfile
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.gmd_utils import (read_gmd, get_strings, set_strings,
                              translate_string, wrap_dialogue_line, _visible)
from tools.arc_utils import read_arc, write_arc
import src.aapatch as aapatch


# ─── Arcs à patcher ─────────────────────────────────────────────────────────
# Chaque entrée : chemin relatif depuis game_root → liste de JSON de traduction.
# Les JSON DGS2 sont découverts automatiquement (glob sur traductions/dgs2/).
# Ajouter une entrée BB/ ici quand une nouvelle scène DGS2 est traduite.

REPO_DIR = Path(__file__).parent.parent

ARC_TRANSLATIONS: dict[str, list[str]] = {
    # ── DGS1 (GO/) ──────────────────────────────────────────────────────────
    'nativeDX11x64/archive/GO/sce00_eng.arc': ['traductions/dgs1/sce00.json'],
    'nativeDX11x64/archive/GO/sce01_eng.arc': ['traductions/dgs1/sce01.json'],
    'nativeDX11x64/archive/GO/sce02_eng.arc': ['traductions/dgs1/sce02.json'],
    'nativeDX11x64/archive/GO/sce03_eng.arc': ['traductions/dgs1/sce03.json'],
    'nativeDX11x64/archive/GO/sce04_eng.arc': ['traductions/dgs1/sce04.json'],
    # ── DGS2 (BB/) ──────────────────────────────────────────────────────────
    'nativeDX11x64/archive/BB/sce00_eng.arc': ['traductions/dgs2/sce00_c000.json'],
    # Ajouter ici au fur et à mesure :
    # 'nativeDX11x64/archive/BB/sce01_eng.arc': ['traductions/dgs2/sce01_c000.json', ...],
    # ── Noms de personnages / UI (GO/) ──────────────────────────────────────
    # Traité depuis l'anglais original — noms, profils dossier, lieux, topics.
    'nativeDX11x64/archive/GO/msg_title_eng.arc': ['traductions/legacy/archive/GO/msg_title_eng.json'],
}


def load_translations(json_paths: list[str]) -> dict[str, dict[str, str]]:
    """
    Charge une liste de JSON et retourne { gmd_short_name: {en: fr} }.
    Plusieurs JSON peuvent couvrir le même arc (ex: plusieurs chapitres DGS2).
    """
    result: dict[str, dict[str, str]] = {}

    for json_path in json_paths:
        full_path = REPO_DIR / json_path
        if not full_path.exists():
            print(f"  AVERTISSEMENT: JSON introuvable : {json_path}")
            continue

        with open(full_path, encoding='utf-8') as f:
            data = json.load(f)

        for gmd_short, entries in data.items():
            replacements: dict[str, str] = {}
            for entry in entries:
                en_raw = entry.get('en', '')
                fr_raw = entry.get('fr', '')
                if not en_raw or not fr_raw:
                    continue

                en_vis = re.sub(r'\s+', ' ',
                                _visible(en_raw).replace('\r\n', ' ').replace('\n', ' ')).strip()
                if not en_vis:
                    continue

                # Strings "full GMD" (contiennent <RDFG>) : pas de wrap ni de
                # validation — le string couvre plusieurs blocs et des codes
                # d'événement, les checks seraient de faux positifs.
                full_gmd = '<RDFG ' in en_raw

                if full_gmd:
                    fr = fr_raw
                else:
                    fr = wrap_dialogue_line(fr_raw.replace('\r\n', '\n')).replace('\n', '\r\n')

                fr_vis = re.sub(r'\s+', ' ',
                                _visible(fr).replace('\r\n', ' ').replace('\n', ' ')).strip()
                if en_vis == fr_vis:
                    continue

                if not full_gmd:
                    entry_id = entry.get('id', '?')

                    for box_part in fr.split('<PAGE>'):
                        if box_part.count('\r\n') + 1 > 2:
                            print(f"  ⚠ DÉPASSEMENT [{gmd_short} #{entry_id}]")
                            break

                    en_codes = set(re.findall(r'<[^>]+>', en_raw))
                    fr_codes = set(re.findall(r'<[^>]+>', fr_raw))
                    missing = en_codes - fr_codes
                    if missing:
                        print(f"  ⚠ CODES MANQUANTS [{gmd_short} #{entry_id}]: {', '.join(sorted(missing))}")

                replacements[en_raw] = fr
                replacements[en_vis] = fr

            if replacements:
                if gmd_short not in result:
                    result[gmd_short] = {}
                result[gmd_short].update(replacements)

    return result


def patch_arc(arc_source: str, gmd_translations: dict[str, dict[str, str]]) -> bytes:
    """Applique les traductions aux GMD d'un ARC, retourne les bytes du nouvel ARC."""
    with open(arc_source, 'rb') as f:
        arc_data = f.read()

    entries = read_arc(arc_data)
    new_entries = []
    modified_count = 0

    for name, raw_gmd in entries:
        short = name.split('\\')[-1]
        if short in gmd_translations:
            replacements = gmd_translations[short]
            gmd = read_gmd(raw_gmd)
            strings = get_strings(gmd)
            strat4_log: list[str] = []
            new_strings = [translate_string(s, replacements, strat4_log) for s in strings]
            new_raw = set_strings(gmd, new_strings)
            new_entries.append((name, new_raw))
            modified_count += 1
            print(f"  ✓ {short}")
            for hit in strat4_log:
                print(f"  ⚠ STRATÉGIE 4 ({short}): {hit}")
        else:
            new_entries.append((name, raw_gmd))

    print(f"  → {modified_count}/{len(entries)} GMD(s) modifié(s)")
    return write_arc(new_entries, arc_data[:8])


def main():
    parser = argparse.ArgumentParser(description='Crée un .aapatch DGS1+DGS2 FR pour Steam')
    parser.add_argument('--game-dir',
                        default='/home/korphos/.steam/debian-installation/steamapps/common/TGAAC',
                        help='Dossier racine du jeu TGAAC')
    parser.add_argument('--output', default='tgaac_fr.aapatch',
                        help='Fichier .aapatch de sortie')
    args = parser.parse_args()

    game_dir = Path(args.game_dir)

    if not (game_dir / 'TGAAC.exe').exists():
        print(f"ERREUR: TGAAC.exe introuvable dans {game_dir}")
        sys.exit(1)

    print("=== Création du patch TGAAC FR (DGS1 + DGS2, Steam) ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = Path(tmpdir) / 'original'
        trad_dir = Path(tmpdir) / 'traduit'
        orig_dir.mkdir()
        trad_dir.mkdir()

        for arc_rel_path, json_paths in ARC_TRANSLATIONS.items():
            arc_abs = game_dir / arc_rel_path
            print(f"--- {arc_rel_path} ---")

            if not arc_abs.exists():
                print(f"  ERREUR: ARC introuvable, ignoré\n")
                continue

            bak_path = arc_abs.with_suffix('.arc.bak')
            if not bak_path.exists():
                shutil.copy2(arc_abs, bak_path)
                print(f"  Backup créé : {bak_path.name}")
            else:
                print(f"  Backup existant : {bak_path.name}")

            # Toujours patcher depuis le backup (source originale propre)
            orig_arc = orig_dir / arc_rel_path
            orig_arc.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak_path, orig_arc)

            gmd_translations = load_translations(json_paths)
            total = sum(len(v) for v in gmd_translations.values())
            print(f"  Traductions : {len(gmd_translations)} GMD(s), {total} remplacements")

            new_arc_bytes = patch_arc(str(bak_path), gmd_translations)

            trad_arc = trad_dir / arc_rel_path
            trad_arc.parent.mkdir(parents=True, exist_ok=True)
            with open(trad_arc, 'wb') as f:
                f.write(new_arc_bytes)

            print(f"  {bak_path.stat().st_size} → {len(new_arc_bytes)} bytes\n")

        print("Génération du .aapatch...")
        patch = aapatch.AAPatch()
        patch.load_origin(str(orig_dir))
        patch.load_destination(str(trad_dir), flag=0)
        patch.flag = 2  # Steam
        patch.write(args.output)
        print(f"\n✓ Patch créé : {args.output}")
        print(f"  Entrées : DGS1 (GO/) + DGS2 (BB/) dans un seul fichier")


if __name__ == '__main__':
    main()
