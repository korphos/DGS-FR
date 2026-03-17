"""
Crée un fichier .aapatch pour DGS2 Steam à partir des traductions JSON.

Usage :
  python3 tools/create_patch_dgs2.py \
      --game-dir /path/to/TGAAC \
      --output dgs2_fr.aapatch

Format des fichiers de traduction (traductions/dgs2/*.json) :
  {
    "_gmd_name": [
      {
        "id": "001",
        "en": "<codes>texte anglais avec codes de contrôle<codes>",
        "fr": "<codes>texte français avec codes aux bons endroits<codes>"
      },
      ...
    ]
  }

  - "en" : contenu brut du bloc <E025>…<E023/PAGE> en anglais (codes inclus)
           → utilisé pour le matching (texte visible extrait automatiquement)
  - "fr" : traduction avec codes de contrôle positionnés par le traducteur
           → remplace directement le contenu du bloc dans le GMD

Pour l'instant seul sce00_c000 (prologue + antichambre ep1) est traité.
"""

import sys
import os
import re
import json
import struct
import zlib
import shutil
import tempfile
import argparse
from pathlib import Path

# Ajout du répertoire racine au path pour importer src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.gmd_utils import read_gmd, get_strings, set_strings, translate_string, wrap_dialogue_line
from tools.arc_utils import read_arc, write_arc
import src.aapatch as aapatch


# ─── Chemins relatifs dans le jeu Steam (depuis game_root/nativeDX11x64/) ────
ARC_FILES = {
    'sce00': 'nativeDX11x64/archive/BB/sce00_eng.arc',
}

# ─── Mapping des noms de fichiers GMD → fichier JSON de traduction ────────────
# Format : { arc_key: { gmd_name: json_path } }
# Chaque JSON contient { "_gmd_name": [ {id, en, fr}, ... ] }
# Le même JSON peut couvrir plusieurs GMD (toutes les entrées sont dans un seul fichier par scène).
TRANSLATION_MAP = {
    'sce00': {
        'BB\\script\\output\\_sce00_c000_0000_eng': 'traductions/dgs2/sce00_c000.json',
        'BB\\script\\output\\_sce00_c000_0010_eng': 'traductions/dgs2/sce00_c000.json',
    }
}


def parse_translation_json(json_path: str, gmd_name: str) -> dict[str, str]:
    """
    Lit un fichier JSON de traduction et retourne un dict {texte_EN_visible: texte_FR}.

    Format JSON :
      { "_gmd_name": [ {"id": "001", "en": "<codes>texte EN<codes>", "fr": "texte FR"} ] }

    - "en" peut contenir les codes de contrôle bruts du GMD (ex: <E007>, <E003 8>…)
      → le texte visible est extrait automatiquement pour le matching
    - "fr" peut contenir des codes positionnés par le traducteur
      → utilisé directement comme contenu du bloc dans le GMD
    - Si "fr" ne contient pas de codes (<), wrap_dialogue_line est appliqué automatiquement
    """
    from tools.gmd_utils import _visible

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    # Chercher la section correspondant à ce GMD (nom complet ou dernier segment)
    gmd_short = gmd_name.split('\\')[-1]
    entries = data.get(gmd_name) or data.get(gmd_short) or data.get('_' + gmd_short)
    if entries is None:
        # Chercher par correspondance partielle
        for key in data:
            if gmd_short in key or key in gmd_name:
                entries = data[key]
                break
    if entries is None:
        return {}

    replacements = {}
    for entry in entries:
        en_raw = entry.get('en', '')
        fr_raw = entry.get('fr', '')
        if not en_raw or not fr_raw:
            continue

        # Extraire le texte EN visible (supprime les codes de contrôle)
        en_vis = re.sub(r'\s+', ' ', _visible(en_raw).replace('\r\n', ' ').replace('\n', ' ')).strip()
        if not en_vis:
            continue

        # Sauts de ligne automatiques — toujours appliqués (gère les codes <...>)
        # Normalisation CRLF→LF avant wrap, puis restauration LF→CRLF
        fr = wrap_dialogue_line(fr_raw.replace('\r\n', '\n')).replace('\n', '\r\n')

        # Ignorer les entrées non traduites (EN visible == FR) — les codes originaux
        # du bloc seront préservés tels quels dans le GMD
        fr_vis = re.sub(r'\s+', ' ', _visible(fr).replace('\r\n', ' ').replace('\n', ' ')).strip()
        if en_vis == fr_vis:
            continue

        # Warning si une boîte dépasse 2 lignes visuelles (après <PAGE> = boîte séparée)
        entry_id = entry.get('id', '?')
        gmd_short_warn = gmd_name.split('\\')[-1]
        for box_part in fr.split('<PAGE>'):
            line_count = box_part.count('\r\n') + 1
            if line_count > 2:
                print(f"  ⚠ DÉPASSEMENT [{gmd_short_warn} #{entry_id}]: {line_count} lignes (max 2 par boîte)")
                break

        # ── Warning : codes présents dans EN mais absents de FR ──────────────
        en_codes = set(re.findall(r'<[^>]+>', en_raw))
        fr_codes = set(re.findall(r'<[^>]+>', fr_raw))
        missing = en_codes - fr_codes
        if missing:
            missing_str = ', '.join(sorted(missing))
            print(f"  ⚠ CODES MANQUANTS [{gmd_short} #{entry_id}]: {missing_str}")

        # Deux clés : contenu brut EN (priorité stratégie 1) + texte visible EN (fallback stratégie 4)
        replacements[en_raw] = fr   # clé brute — stratégie 1 matchera directement
        replacements[en_vis] = fr   # clé visible — fallback pour stratégie 4

    return replacements


def _check_untranslated(original: bytes, translated: bytes,
                        replacements: dict[str, str],
                        warnings: list[str]) -> None:
    """
    Émet un warning si une string de dialogue anglaise connue n'a pas été traduite.
    Compare les blocs <E025>...<E023/PAGE> : si le texte visible du résultat
    correspond à une clé anglaise du dict de traductions, c'est qu'il n'a pas été
    remplacé.
    """
    if original == translated:
        return
    try:
        orig_text = original.decode('utf-8')
        trad_text = translated.decode('utf-8')
    except UnicodeDecodeError:
        return

    # Textes visibles des blocs dans le résultat traduit
    for m in re.finditer(r'<E025[^>]*>(.*?)(<E023>|<PAGE>)', trad_text, re.DOTALL):
        vis = re.sub(r'<[^>]+>', '', m.group(1)).replace('\r\n', ' ').replace('\n', ' ').strip()
        vis_norm = re.sub(r'\s+', ' ', vis)
        if not vis_norm or len(vis_norm) < 4:
            continue
        # Si ce texte visible correspond à une clé EN connue → non traduit
        for en in replacements:
            en_norm = re.sub(r'\s+', ' ', en.replace('\r\n', ' ').replace('\n', ' ')).strip()
            if en_norm == vis_norm:
                warnings.append(repr(vis_norm[:80]))
                break


def patch_arc(arc_path: str, gmd_translations: dict[str, dict[str, str]]) -> bytes:
    """
    Prend un ARC original, applique les traductions aux GMD concernés,
    et retourne les bytes du nouvel ARC modifié.

    gmd_translations = { gmd_name: {en_text: fr_text} }
    """
    with open(arc_path, 'rb') as f:
        arc_data = f.read()

    entries = read_arc(arc_data)
    new_entries = []

    modified_count = 0
    for name, raw_gmd in entries:
        if name in gmd_translations:
            replacements = gmd_translations[name]
            gmd = read_gmd(raw_gmd)
            strings = get_strings(gmd)

            new_strings = []
            untranslated = []
            strat4_log: list[str] = []
            for s in strings:
                new_s = translate_string(s, replacements, strat4_log)
                new_strings.append(new_s)
                # Détection d'anglais résiduel : dialogue non traduit
                _check_untranslated(s, new_s, replacements, untranslated)

            new_raw_gmd = set_strings(gmd, new_strings)
            new_entries.append((name, new_raw_gmd))
            modified_count += 1
            gmd_short = name.split(chr(92))[-1]
            print(f"  ✓ GMD modifié : {gmd_short}")
            for warn in untranslated:
                print(f"  ⚠ NON TRADUIT ({gmd_short}): {warn}")
            for hit in strat4_log:
                print(f"  ⚠ STRATÉGIE 4 ({gmd_short}): {hit}")
        else:
            new_entries.append((name, raw_gmd))

    print(f"  {modified_count} GMD(s) modifié(s) sur {len(entries)}")
    return write_arc(new_entries, arc_data[:8])


def main():
    parser = argparse.ArgumentParser(description='Crée un .aapatch DGS2 FR pour Steam')
    parser.add_argument('--game-dir', required=True,
                        help='Dossier racine du jeu TGAAC (contenant TGAAC.exe)')
    parser.add_argument('--output', default='dgs2_fr_test.aapatch',
                        help='Fichier .aapatch de sortie')
    args = parser.parse_args()

    game_dir = Path(args.game_dir)
    repo_dir = Path(__file__).parent.parent

    if not (game_dir / 'TGAAC.exe').exists():
        print(f"ERREUR: TGAAC.exe introuvable dans {game_dir}")
        sys.exit(1)

    print("=== Création du patch DGS2 FR (Steam) ===\n")

    # Dossiers temporaires pour original et traduit
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = Path(tmpdir) / 'original'
        trad_dir = Path(tmpdir) / 'traduit'
        orig_dir.mkdir()
        trad_dir.mkdir()

        for arc_key, arc_rel_path in ARC_FILES.items():
            arc_abs = game_dir / arc_rel_path

            if not arc_abs.exists():
                print(f"ERREUR: ARC introuvable : {arc_abs}")
                sys.exit(1)

            # Sauvegarde de l'original à côté du fichier jeu (une seule fois)
            backup_arc = Path(str(arc_abs) + '.bak')
            if not backup_arc.exists():
                shutil.copy2(arc_abs, backup_arc)
                print(f"  Backup créé : {backup_arc}")
            else:
                print(f"  Backup existant : {backup_arc}")

            # Utilise toujours le backup comme source "original"
            arc_source = backup_arc

            print(f"Traitement de {arc_rel_path}...")

            # Copie l'original (depuis le backup)
            orig_arc = orig_dir / arc_rel_path
            orig_arc.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arc_source, orig_arc)

            # Construit le mapping gmd_name → replacements
            gmd_translations = {}
            if arc_key in TRANSLATION_MAP:
                loaded_json: dict[str, dict] = {}  # cache json_path → data parsed
                for gmd_name, json_rel_path in TRANSLATION_MAP[arc_key].items():
                    json_path = repo_dir / json_rel_path
                    if json_path.exists():
                        replacements = parse_translation_json(str(json_path), gmd_name)
                        gmd_translations[gmd_name] = replacements
                        print(f"  Traduction chargée : {json_path.name} [{gmd_name.split(chr(92))[-1]}]"
                              f" ({len(replacements)} remplacements)")
                    else:
                        print(f"  AVERTISSEMENT: JSON introuvable : {json_path}")

            # Crée le nouvel ARC traduit (depuis le backup, pas le fichier jeu)
            new_arc_bytes = patch_arc(str(arc_source), gmd_translations)

            trad_arc = trad_dir / arc_rel_path
            trad_arc.parent.mkdir(parents=True, exist_ok=True)
            with open(trad_arc, 'wb') as f:
                f.write(new_arc_bytes)

            print(f"  ARC original : {len(open(arc_abs,'rb').read())} bytes")
            print(f"  ARC traduit  : {len(new_arc_bytes)} bytes\n")

        # Crée le .aapatch
        print("Génération du .aapatch...")
        patch = aapatch.AAPatch()
        patch.load_origin(str(orig_dir))
        patch.load_destination(str(trad_dir), flag=0)  # flag=0 dans load_destination
        patch.flag = 2  # flag=2 = STM (Steam) dans le header .aapatch
        patch.write(args.output)
        print(f"\n✓ Patch créé : {args.output}")


if __name__ == '__main__':
    main()
