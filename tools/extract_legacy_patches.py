#!/usr/bin/env python3
"""
Extrait les données du patch Steam (patch_steam.aapatch) pour les fichiers
NON couverts par nos JSON de scènes, et les stocke dans le dépôt :

  - assets/patches/<chemin_relatif>.bsdiff  : patch bsdiff brut
  - assets/patches/manifest.json           : hash + taille de chaque bsdiff
  - traductions/legacy/<nom_simplifié>.json : paires EN→FR (GMD seulement)

Usage :
  python3 tools/extract_legacy_patches.py [--patch <path>] [--game-dir <path>]
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path

import bsdiff4
from xxhash import xxh32_digest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.aapatch import AAPatch
from src.utils import EndianBinaryFileReader
from tools.arc_utils import read_arc
from tools.gmd_utils import read_gmd, get_strings


# ─── Scènes gérées par nos JSON (à ignorer) ──────────────────────────────────

OUR_SCENES = {
    'nativeDX11x64/archive/GO/sce00_eng.arc',
    'nativeDX11x64/archive/GO/sce01_eng.arc',
    'nativeDX11x64/archive/GO/sce02_eng.arc',
    'nativeDX11x64/archive/GO/sce03_eng.arc',
    'nativeDX11x64/archive/GO/sce04_eng.arc',
    'nativeDX11x64/archive/BB/sce00_eng.arc',
}

REPO_DIR   = Path(__file__).parent.parent
GAME_DIR   = Path('/home/korphos/.steam/debian-installation/steamapps/common/TGAAC')
PATCH_PATH = Path('/home/korphos/Downloads/patch_steam.aapatch')


# ─── Helpers ─────────────────────────────────────────────────────────────────

def file_hash(data: bytes) -> bytes:
    """Retourne le hash xxh32 (4 bytes) des données."""
    return xxh32_digest(data)


def _rel_to_output_key(rel: str) -> str:
    """Transforme un chemin relatif en clé manifeste normalisée (slashes UNIX)."""
    return rel.replace('\\', '/')


def _rel_to_legacy_json_path(rel: str) -> Path:
    """
    Convertit un chemin relatif de jeu en chemin de JSON legacy.
    Ex: 'nativeDX11x64/archive/msg_cmn_eng.arc'
        → traductions/legacy/archive/msg_cmn_eng.json
    Strip le préfixe 'nativeDX11x64/' s'il est présent.
    """
    rel_clean = rel.replace('\\', '/')
    if rel_clean.startswith('nativeDX11x64/'):
        rel_clean = rel_clean[len('nativeDX11x64/'):]
    # Change l'extension en .json
    stem = rel_clean.rsplit('.', 1)[0] if '.' in rel_clean else rel_clean
    return REPO_DIR / 'traductions' / 'legacy' / (stem + '.json')


def _compare_gmd_bytes(en_raw: bytes, fr_raw: bytes,
                       gmd_short: str) -> list[dict]:
    """
    Compare deux GMD (EN vs FR) et retourne les paires de traduction.
    """
    if en_raw == fr_raw:
        return []

    try:
        en_gmd = read_gmd(en_raw)
        fr_gmd = read_gmd(fr_raw)
    except AssertionError:
        return []

    en_strings = get_strings(en_gmd)
    fr_strings = get_strings(fr_gmd)

    if len(en_strings) != len(fr_strings):
        print(f"    ! {gmd_short}: nombre de strings différent "
              f"({len(en_strings)} vs {len(fr_strings)}), ignoré")
        return []

    entries = []
    counter = 1
    for en_s, fr_s in zip(en_strings, fr_strings):
        if en_s == fr_s:
            continue
        try:
            en_text = en_s.decode('utf-8')
            fr_text = fr_s.decode('utf-8')
        except UnicodeDecodeError:
            continue

        # Ignorer les strings sans texte visible
        en_vis = re.sub(r'<[^>]+>', '', en_text).strip()
        fr_vis = re.sub(r'<[^>]+>', '', fr_text).strip()
        if not en_vis and not fr_vis:
            continue

        entries.append({
            'id': f'{counter:03d}',
            'en': en_text,
            'fr': fr_text,
        })
        counter += 1

    return entries


def extract_translations_from_arc(en_arc: bytes,
                                   fr_arc: bytes) -> dict[str, list[dict]]:
    """
    Compare deux ARC (EN original et FR patché).
    Retourne { gmd_short_name: [{id, en, fr}, ...] }.
    """
    try:
        en_entries = read_arc(en_arc)
        fr_entries = read_arc(fr_arc)
    except Exception as ex:
        print(f"    ! Impossible de parser l'ARC : {ex}")
        return {}

    result: dict[str, list[dict]] = {}

    for (en_name, en_raw), (fr_name, fr_raw) in zip(en_entries, fr_entries):
        if en_raw[:4] != b'GMD\x00':
            continue

        short = en_name.split('\\')[-1]
        pairs = _compare_gmd_bytes(en_raw, fr_raw, short)
        if pairs:
            result[short] = pairs
            print(f"    {short}: {len(pairs)} traduction(s)")

    return result


def extract_translations_from_gmd(en_raw: bytes, fr_raw: bytes,
                                   gmd_short: str) -> dict[str, list[dict]]:
    """Compare deux GMD directs. Retourne { gmd_short: [{id, en, fr}, ...] }."""
    pairs = _compare_gmd_bytes(en_raw, fr_raw, gmd_short)
    if pairs:
        print(f"    {gmd_short}: {len(pairs)} traduction(s)")
        return {gmd_short: pairs}
    return {}


# ─── Programme principal ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Extrait les bsdiffs et traductions legacy du patch Steam'
    )
    parser.add_argument(
        '--patch',
        default=str(PATCH_PATH),
        help='Chemin vers patch_steam.aapatch',
    )
    parser.add_argument(
        '--game-dir',
        default=str(GAME_DIR),
        help='Dossier racine du jeu TGAAC',
    )
    args = parser.parse_args()

    patch_path = Path(args.patch)
    game_dir   = Path(args.game_dir)

    if not patch_path.exists():
        print(f"ERREUR : patch introuvable : {patch_path}")
        sys.exit(1)

    if not game_dir.exists():
        print(f"ERREUR : game-dir introuvable : {game_dir}")
        sys.exit(1)

    patches_dir = REPO_DIR / 'assets' / 'patches'
    patches_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Extraction du patch legacy ===")
    print(f"Patch    : {patch_path}")
    print(f"Jeu      : {game_dir}")
    print(f"Bsdiffs  : {patches_dir}")
    print()

    p = AAPatch()
    p.read(str(patch_path))
    print(f"Patch chargé : {len(p.entries)} entrées\n")

    manifest: dict[str, dict] = {}
    json_count   = 0
    files_saved  = 0
    total_bsdiff = 0
    errors       = 0

    with EndianBinaryFileReader(str(patch_path)) as patch_f:
        for entry in p.entries:
            rel = entry.filepath.replace('\\', '/')

            # Ignorer nos scènes
            if rel in OUR_SCENES:
                continue

            target = game_dir / rel
            bak    = target.with_suffix(target.suffix + '.bak')
            src    = bak if bak.exists() else target

            if not src.exists():
                print(f"  ⚠ introuvable : {rel}")
                errors += 1
                continue

            # Lire l'original (backup en priorité)
            orig_bytes = src.read_bytes()
            expected_hash = entry.files[0].hash

            if file_hash(orig_bytes) != expected_hash:
                print(f"  ⚠ hash inattendu : {rel} "
                      f"(actuel={file_hash(orig_bytes).hex()}, "
                      f"attendu={expected_hash.hex()})")
                # On continue quand même — on stocke quand même le bsdiff

            # Lire le patch bsdiff brut depuis le .aapatch
            pf = entry.files[0]
            patch_f.seek(p.base_data_offset + pf.offset)
            patch_data = patch_f.read(pf.data_size)

            # ── Sauvegarder le bsdiff brut ────────────────────────────────
            bsdiff_out = patches_dir / rel
            bsdiff_out = bsdiff_out.parent / (bsdiff_out.name + '.bsdiff')
            bsdiff_out.parent.mkdir(parents=True, exist_ok=True)
            bsdiff_out.write_bytes(patch_data)
            files_saved  += 1
            total_bsdiff += len(patch_data)

            key = _rel_to_output_key(rel)
            manifest[key] = {
                'hash':        expected_hash.hex(),
                'bsdiff_size': len(patch_data),
            }

            # ── Extraire les traductions (GMD) ────────────────────────────
            translations: dict[str, list[dict]] = {}

            if rel.endswith('.arc'):
                # Appliquer le patch en mémoire pour comparer EN vs FR
                try:
                    fr_bytes = bsdiff4.patch(orig_bytes, patch_data)
                except Exception as ex:
                    print(f"  ⚠ bsdiff4.patch échoué pour {rel}: {ex}")
                    continue

                # Cherche les GMD dans l'ARC patché
                try:
                    en_entries_arc = read_arc(orig_bytes)
                    has_gmd = any(raw[:4] == b'GMD\x00' for _, raw in en_entries_arc)
                except Exception:
                    has_gmd = False

                if has_gmd:
                    print(f"  {rel}")
                    translations = extract_translations_from_arc(orig_bytes, fr_bytes)

            elif rel.endswith('.gmd'):
                try:
                    fr_bytes = bsdiff4.patch(orig_bytes, patch_data)
                except Exception as ex:
                    print(f"  ⚠ bsdiff4.patch échoué pour {rel}: {ex}")
                    continue

                if orig_bytes[:4] == b'GMD\x00':
                    gmd_short = Path(rel).stem
                    print(f"  {rel}")
                    translations = extract_translations_from_gmd(
                        orig_bytes, fr_bytes, gmd_short
                    )

            if translations:
                total_pairs = sum(len(v) for v in translations.values())
                json_path = _rel_to_legacy_json_path(rel)
                json_path.parent.mkdir(parents=True, exist_ok=True)
                with open(json_path, 'w', encoding='utf-8') as jf:
                    json.dump(translations, jf, ensure_ascii=False, indent=2)
                print(f"    → JSON : {json_path.relative_to(REPO_DIR)} "
                      f"({total_pairs} paires)")
                json_count += 1

    # Sauvegarder le manifeste
    manifest_path = patches_dir / 'manifest.json'
    with open(manifest_path, 'w', encoding='utf-8') as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)

    print()
    print(f"=== Résultats ===")
    print(f"  Bsdiffs sauvegardés : {files_saved}")
    print(f"  JSON créés          : {json_count}")
    print(f"  Taille totale bsdiff: {total_bsdiff / 1024 / 1024:.1f} Mo")
    print(f"  Erreurs             : {errors}")
    print(f"  Manifeste           : {manifest_path.relative_to(REPO_DIR)}")


if __name__ == '__main__':
    main()
