#!/usr/bin/env python3
"""
Régénère le patch TGAAC FR (DGS1 + DGS2) et l'applique directement au jeu.
Applique aussi les fichiers UI/polices/messages de l'ancien patch.

Usage :
  python3 rebuild_and_apply.py
"""

import sys
import json
import shutil
import bsdiff4
from pathlib import Path
from xxhash import xxh32_digest

sys.path.insert(0, str(Path(__file__).parent))

import tools.create_patch as cp

GAME_DIR   = Path('/home/korphos/.steam/debian-installation/steamapps/common/TGAAC')
PATCH_PATH = Path(__file__).parent / 'tgaac_fr.aapatch'
REPO_DIR   = Path(__file__).parent

# Dossier contenant les bsdiffs pré-extraits + manifest
PATCHES_DIR = REPO_DIR / 'assets' / 'patches'

# Arcs couverts par notre patch de scènes
OUR_SCENE_ARCS = set(cp.ARC_TRANSLATIONS.keys())

# GMDs bruts gérés via JSON (exclus du bsdiff legacy)
OUR_GMD_PATHS = set(cp.GMD_TRANSLATIONS.keys())


def file_hash(data: bytes) -> bytes:
    return xxh32_digest(data)


def apply_non_scene_from_original():
    """
    Applique les fichiers UI/polices/messages depuis les bsdiffs pré-extraits
    (assets/patches/).  Crée les .bak si absents, restaure depuis .bak avant
    chaque application.
    """
    manifest_path = PATCHES_DIR / 'manifest.json'
    if not manifest_path.exists():
        print(f"  ERREUR : manifeste introuvable : {manifest_path}")
        print("  Lancez d'abord : python3 tools/extract_legacy_patches.py")
        return

    with open(manifest_path, encoding='utf-8') as mf:
        manifest: dict = json.load(mf)

    applied, errors = 0, 0

    for rel, meta in manifest.items():
        # Ignorer nos scènes et GMDs gérés via JSON
        if rel in OUR_SCENE_ARCS or rel in OUR_GMD_PATHS:
            continue

        target = GAME_DIR / rel
        if not target.exists():
            errors += 1
            print(f"  ⚠ introuvable : {rel}")
            continue

        bak = target.with_suffix(target.suffix + '.bak')
        expected_hash = bytes.fromhex(meta['hash'])

        # Créer le backup si le fichier est encore l'original
        if not bak.exists():
            if file_hash(target.read_bytes()) == expected_hash:
                shutil.copy2(target, bak)
            else:
                errors += 1
                print(f"  ⚠ hash inattendu, backup manquant : {rel}")
                continue

        # Restaurer depuis le backup (garantit qu'on part de l'original)
        shutil.copy2(bak, target)

        if file_hash(target.read_bytes()) != expected_hash:
            errors += 1
            print(f"  ⚠ hash incorrect même après restauration : {rel}")
            continue

        # Lire le bsdiff pré-extrait
        bsdiff_path = PATCHES_DIR / (rel + '.bsdiff')
        if not bsdiff_path.exists():
            errors += 1
            print(f"  ⚠ bsdiff manquant : {bsdiff_path}")
            continue

        patch_data = bsdiff_path.read_bytes()
        patched = bsdiff4.patch(target.read_bytes(), patch_data)
        target.write_bytes(patched)
        applied += 1

    print(f"  {applied} fichiers UI/non-scènes appliqués"
          + (f", {errors} erreur(s)" if errors else ""))


def apply_gmd_translations():
    """
    Patche les GMDs bruts de GO/msg/ depuis les JSON de traduction.
    Remplace le bsdiff legacy pour ces fichiers.
    Crée les .gmd.bak si absents, repart toujours de l'original.
    """
    applied, errors = 0, 0

    for gmd_rel, json_paths in cp.GMD_TRANSLATIONS.items():
        gmd_abs = GAME_DIR / gmd_rel
        if not gmd_abs.exists():
            errors += 1
            print(f"  ⚠ GMD introuvable : {gmd_rel}")
            continue

        bak_path = Path(str(gmd_abs) + '.bak')
        if not bak_path.exists():
            shutil.copy2(gmd_abs, bak_path)

        is_dgs2 = any('dgs2' in p for p in json_paths)
        gmd_translations = cp.load_translations(json_paths, warn_overflow=is_dgs2)
        new_bytes = cp.patch_gmd_file(str(bak_path), gmd_translations)
        gmd_abs.write_bytes(new_bytes)
        applied += 1

    print(f"  {applied} GMD(s) patchés depuis JSON"
          + (f", {errors} erreur(s)" if errors else ""))


def build_and_apply_scene_patch():
    """
    Régénère tgaac_fr.aapatch depuis les JSON de traductions
    et l'applique sur les arcs de scènes.
    """
    import re, tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        orig_dir = Path(tmpdir) / 'original'
        trad_dir = Path(tmpdir) / 'traduit'
        orig_dir.mkdir()
        trad_dir.mkdir()

        for arc_rel_path, json_paths in cp.ARC_TRANSLATIONS.items():
            arc_abs = GAME_DIR / arc_rel_path
            if not arc_abs.exists():
                print(f"  ⚠ ARC introuvable : {arc_rel_path}")
                continue

            bak_path = arc_abs.with_suffix('.arc.bak')
            if not bak_path.exists():
                shutil.copy2(arc_abs, bak_path)

            orig_arc = orig_dir / arc_rel_path
            orig_arc.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bak_path, orig_arc)

            is_dgs2 = any('dgs2' in p for p in json_paths)
            gmd_translations = cp.load_translations(json_paths, warn_overflow=is_dgs2)
            total = sum(len(v) for v in gmd_translations.values())
            short = Path(arc_rel_path).name
            print(f"  {short} : {len(gmd_translations)} GMD(s), {total} remplacements")

            new_arc_bytes = cp.patch_arc(str(bak_path), gmd_translations)

            trad_arc = trad_dir / arc_rel_path
            trad_arc.parent.mkdir(parents=True, exist_ok=True)
            trad_arc.write_bytes(new_arc_bytes)

        print(f"\n  Calcul des diffs bsdiff...")
        import src.aapatch as aapatch_mod
        patch = aapatch_mod.AAPatch()
        patch.load_origin(str(orig_dir))
        patch.load_destination(str(trad_dir), flag=0)
        patch.flag = 2
        patch.write(str(PATCH_PATH))

    print(f"  Patch généré : {PATCH_PATH.name}")

    # Restaurer les originaux puis appliquer
    for arc_rel in OUR_SCENE_ARCS:
        target = GAME_DIR / arc_rel
        backup = target.with_suffix('.arc.bak')
        if backup.exists():
            shutil.copy2(backup, target)

    p = aapatch_mod.AAPatch()
    p.read(str(PATCH_PATH))
    p.patch_all(str(GAME_DIR), flags=[2])


def main():
    print("=== Étape 1 : UI, polices, messages (patch original) ===")
    apply_non_scene_from_original()

    print("\n=== Étape 1b : GMDs GO/msg/ (traductions JSON) ===")
    apply_gmd_translations()

    print("\n=== Étape 2 : dialogues de scènes (nos traductions JSON) ===")
    build_and_apply_scene_patch()

    print("\n✓ Tout appliqué. Bonne partie !")


if __name__ == '__main__':
    main()
