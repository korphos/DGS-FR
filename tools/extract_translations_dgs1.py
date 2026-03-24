"""
Extrait les traductions françaises du patch DGS1 (Steam) et les écrit en JSON.

Usage :
  python3 tools/extract_translations_dgs1.py \\
      --patch /home/korphos/Downloads/patch_steam.aapatch \\
      --game-dir /home/korphos/.steam/debian-installation/steamapps/common/TGAAC \\
      --output-dir traductions/dgs1

Prérequis : les fichiers GO/*.arc doivent être les ORIGINAUX anglais (vérifier
l'intégrité via Steam avant de lancer ce script).

Le script :
1. Vérifie que les hash correspondent aux originaux attendus par le patch
2. Crée les backups .arc.bak des originaux
3. Applique le patch en mémoire (bsdiff) → version française
4. Compare les strings GMD (EN vs FR) et extrait les paires de traduction
5. Écrit les JSON dans traductions/dgs1/<scene>.json
6. Ré-applique le patch sur les fichiers du jeu (restaure la version FR)
"""

import sys
import os
import re
import json
import shutil
import argparse
from pathlib import Path

import bsdiff4

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.aapatch import AAPatch
from src.utils import EndianBinaryFileReader, get_file_hash
from tools.arc_utils import read_arc
from tools.gmd_utils import read_gmd, get_strings


# Scenes à extraire (sce*.arc seulement — dialogue principal)
SCENE_ARCS = [
    'nativeDX11x64/archive/GO/sce00_eng.arc',
    'nativeDX11x64/archive/GO/sce01_eng.arc',
    'nativeDX11x64/archive/GO/sce02_eng.arc',
    'nativeDX11x64/archive/GO/sce03_eng.arc',
    'nativeDX11x64/archive/GO/sce04_eng.arc',
]


def extract_scene_key(arc_rel_path: str) -> str:
    """Extrait la clé de scène depuis le chemin (ex: 'sce00')."""
    name = Path(arc_rel_path).stem  # 'sce00_eng'
    return name.replace('_eng', '')  # 'sce00'


def compare_and_extract(en_arc: bytes, fr_arc: bytes) -> dict[str, list[dict]]:
    """
    Compare deux ARC (original EN et patché FR), extrait les paires de traduction.

    Retourne { gmd_short_name: [ {id, en, fr}, ... ] }
    """
    en_entries = read_arc(en_arc)
    fr_entries = read_arc(fr_arc)

    result: dict[str, list[dict]] = {}

    for (en_name, en_raw), (fr_name, fr_raw) in zip(en_entries, fr_entries):
        assert en_name == fr_name, f"Mismatch de noms GMD: {en_name} vs {fr_name}"

        if en_raw == fr_raw:
            continue  # GMD non modifié, pas de traductions ici

        en_gmd = read_gmd(en_raw)
        fr_gmd = read_gmd(fr_raw)
        en_strings = get_strings(en_gmd)
        fr_strings = get_strings(fr_gmd)

        assert len(en_strings) == len(fr_strings), (
            f"{en_name}: nombre de strings différent ({len(en_strings)} vs {len(fr_strings)})"
        )

        entries = []
        counter = 1
        for en_s, fr_s in zip(en_strings, fr_strings):
            if en_s == fr_s:
                continue  # string non modifiée

            try:
                en_text = en_s.decode('utf-8')
                fr_text = fr_s.decode('utf-8')
            except UnicodeDecodeError:
                continue  # binaire, on ignore

            # Ignorer les strings sans texte visible (pur contrôle)
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

        if entries:
            # Clé courte (nom de fichier sans chemin, ex: '_sce00_c001_0000_eng')
            short = en_name.split('\\')[-1]
            result[short] = entries
            print(f"  {short}: {len(entries)} traduction(s) extraite(s)")

    return result


def main():
    parser = argparse.ArgumentParser(description='Extrait les traductions DGS1 du patch Steam')
    parser.add_argument('--patch', default='/home/korphos/Downloads/patch_steam.aapatch',
                        help='Chemin vers le fichier .aapatch')
    parser.add_argument('--game-dir',
                        default='/home/korphos/.steam/debian-installation/steamapps/common/TGAAC',
                        help='Dossier racine du jeu TGAAC')
    parser.add_argument('--output-dir', default='traductions/dgs1',
                        help='Dossier de sortie pour les JSON')
    parser.add_argument('--skip-verify', action='store_true',
                        help='Ne pas vérifier les hash (dangereux)')
    args = parser.parse_args()

    game_dir = Path(args.game_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Extraction des traductions DGS1 ===\n")
    print(f"Patch : {args.patch}")
    print(f"Jeu   : {game_dir}")
    print(f"Sortie: {output_dir}\n")

    # Charger le patch
    p = AAPatch()
    p.read(args.patch)
    print(f"Patch chargé : {len(p.entries)} entrées\n")

    # Index du patch par chemin relatif
    patch_index = {e.filepath.replace('\\', '/'): e for e in p.entries}

    errors = []
    patched_data: dict[str, bytes] = {}  # chemin relatif → bytes patchés

    for arc_rel_path in SCENE_ARCS:
        arc_abs = game_dir / arc_rel_path
        scene_key = extract_scene_key(arc_rel_path)

        print(f"--- {arc_rel_path} ---")

        if not arc_abs.exists():
            print(f"  ERREUR: fichier introuvable : {arc_abs}")
            errors.append(arc_rel_path)
            continue

        entry = patch_index.get(arc_rel_path)
        if entry is None:
            print(f"  AVERTISSEMENT: non présent dans le patch, ignoré")
            continue

        # Lire l'original
        with open(arc_abs, 'rb') as f:
            ori_bytes = f.read()

        # Vérifier le hash si demandé
        if not args.skip_verify:
            file_hash = get_file_hash(arc_abs)
            expected_hash = entry.files[0].hash
            if file_hash != expected_hash:
                print(f"  ERREUR: hash incorrect (actuel={file_hash.hex()}, attendu={expected_hash.hex()})")
                print(f"  → Vérifiez l'intégrité des fichiers Steam avant de lancer ce script.")
                errors.append(arc_rel_path)
                continue
            print(f"  ✓ Hash vérifié")

        # Créer le backup
        bak_path = arc_abs.with_suffix('.arc.bak')
        if not bak_path.exists():
            shutil.copy2(arc_abs, bak_path)
            print(f"  ✓ Backup créé : {bak_path.name}")
        else:
            print(f"  Backup existant : {bak_path.name}")

        # Appliquer le patch en mémoire
        with EndianBinaryFileReader(args.patch) as f:
            patch_file = entry.files[0]
            f.seek(p.base_data_offset + patch_file.offset)
            patch_data = f.read(patch_file.data_size)

        fr_bytes = bsdiff4.patch(ori_bytes, patch_data)
        patched_data[arc_rel_path] = fr_bytes
        print(f"  ✓ Patch appliqué en mémoire ({len(ori_bytes)} → {len(fr_bytes)} bytes)")

        # Extraire les traductions
        translations = compare_and_extract(ori_bytes, fr_bytes)

        if not translations:
            print(f"  Aucune traduction trouvée.")
            continue

        total = sum(len(v) for v in translations.values())
        print(f"  Total: {total} paires EN/FR sur {len(translations)} GMD(s)")

        # Écrire le JSON
        json_path = output_dir / f"{scene_key}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(translations, f, ensure_ascii=False, indent=2)
        print(f"  ✓ JSON écrit : {json_path}")

    # Ré-appliquer le patch sur les fichiers du jeu
    print(f"\n=== Ré-application du patch FR ===")
    for arc_rel_path, fr_bytes in patched_data.items():
        arc_abs = game_dir / arc_rel_path
        with open(arc_abs, 'wb') as f:
            f.write(fr_bytes)
        print(f"  ✓ {arc_rel_path}")

    if errors:
        print(f"\n⚠ {len(errors)} fichier(s) en erreur : {errors}")
        print("  Vérifiez l'intégrité des fichiers Steam et relancez le script.")
    else:
        print(f"\n✓ Extraction terminée. JSON dans : {output_dir}/")
        print("✓ Patch FR ré-appliqué sur les fichiers du jeu.")


if __name__ == '__main__':
    main()
