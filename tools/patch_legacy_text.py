"""
Applique des remplacements texte dans les fichiers legacy (bsdiffs + JSONs).

Usage :
  # Remplacements passés en ligne de commande (paires ancien→nouveau) :
  python3 tools/patch_legacy_text.py "ancien texte" "nouveau texte" ["ancien2" "nouveau2" ...]

  # Exemple :
  python3 tools/patch_legacy_text.py "Sherlock Holmes" "Herlock Sholmes" "Holmes" "Sholmes"

Pour chaque fichier bsdiff dans assets/patches/ :
  1. Applique le bsdiff sur le backup .bak → bytes FR actuels
  2. Cherche les chaînes à remplacer (dans les GMD des ARCs ou des GMDs directs)
  3. Si trouvé : régénère le bsdiff, met à jour manifest.json et traductions/legacy/*.json
"""

import json
import struct
import sys
from pathlib import Path

import bsdiff4

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.gmd_utils import read_gmd, get_strings, set_strings
from tools.arc_utils import read_arc, write_arc

REPO    = Path(__file__).parent.parent
GAME    = Path('/home/korphos/.steam/debian-installation/steamapps/common/TGAAC')
PATCHES = REPO / 'assets' / 'patches'
LEGACY  = REPO / 'traductions' / 'legacy'


def apply_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def fix_gmd_bytes(gmd_bytes: bytes,
                  replacements: list[tuple[str, str]]) -> tuple[bytes, int]:
    gmd = read_gmd(gmd_bytes)
    strings = get_strings(gmd)
    changed = 0
    new_strings = []
    for s in strings:
        try:
            text = s.decode('utf-8')
        except UnicodeDecodeError:
            new_strings.append(s)
            continue
        fixed = apply_replacements(text, replacements)
        if fixed != text:
            changed += 1
        new_strings.append(fixed.encode('utf-8'))
    return set_strings(gmd, new_strings), changed


def fix_arc_bytes(arc_bytes: bytes,
                  replacements: list[tuple[str, str]]) -> tuple[bytes, int]:
    entries = read_arc(arc_bytes)
    new_entries = []
    total = 0
    for name, raw in entries:
        if raw[:4] == b'GMD\x00':
            fixed_raw, n = fix_gmd_bytes(raw, replacements)
            new_entries.append((name, fixed_raw))
            total += n
        else:
            new_entries.append((name, raw))
    # Preserve original data_start alignment
    first_offset = struct.unpack_from('<I', arc_bytes, 8 + 140)[0]
    return write_arc(new_entries, arc_bytes[:8], data_start=first_offset), total


def update_legacy_json(json_path: Path,
                       replacements: list[tuple[str, str]]) -> int:
    if not json_path.exists():
        return 0
    data = json.loads(json_path.read_text(encoding='utf-8'))
    changed = 0
    for entries in data.values():
        for e in entries:
            if 'fr' in e:
                fixed = apply_replacements(e['fr'], replacements)
                if fixed != e['fr']:
                    e['fr'] = fixed
                    changed += 1
    if changed:
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding='utf-8')
    return changed


def process_all(replacements: list[tuple[str, str]]) -> None:
    manifest = json.loads((PATCHES / 'manifest.json').read_text(encoding='utf-8'))
    total_files = 0

    for rel in sorted(manifest.keys()):
        game_path   = GAME / rel
        bak_path    = Path(str(game_path) + '.bak')
        bsdiff_path = PATCHES / (rel + '.bsdiff')

        if not bak_path.exists() or not bsdiff_path.exists():
            continue

        orig_bytes = bak_path.read_bytes()
        try:
            fr_bytes = bsdiff4.patch(orig_bytes, bsdiff_path.read_bytes())
        except Exception as e:
            print(f'  ⚠ bsdiff4.patch échoué ({rel}): {e}')
            continue

        if rel.endswith('.arc'):
            fixed_bytes, n_changed = fix_arc_bytes(fr_bytes, replacements)
        elif rel.endswith('.gmd'):
            fixed_bytes, n_changed = fix_gmd_bytes(fr_bytes, replacements)
        else:
            continue

        if n_changed == 0:
            continue

        new_patch = bsdiff4.diff(orig_bytes, fixed_bytes)
        bsdiff_path.write_bytes(new_patch)
        manifest[rel]['bsdiff_size'] = len(new_patch)

        rel_clean = rel
        if rel_clean.startswith('nativeDX11x64/'):
            rel_clean = rel_clean[len('nativeDX11x64/'):]
        stem = rel_clean.rsplit('.', 1)[0]
        legacy_json = LEGACY / (stem + '.json')
        update_legacy_json(legacy_json, replacements)

        name = rel.split('/')[-1]
        print(f'  ✓ {name:45} {n_changed} string(s)')
        total_files += 1

    (PATCHES / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'\n{total_files} fichier(s) modifié(s).')


def main() -> None:
    args = sys.argv[1:]
    if not args or len(args) % 2 != 0:
        print('Usage: python3 tools/patch_legacy_text.py "ancien" "nouveau" ...')
        print('Les paires sont appliquées dans l\'ordre (la plus longue en premier).')
        sys.exit(1)

    replacements = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    # Trier par longueur décroissante pour éviter les remplacements partiels
    replacements.sort(key=lambda x: -len(x[0]))

    print('=== Remplacement dans les fichiers legacy ===')
    for old, new in replacements:
        print(f'  {old!r} → {new!r}')
    print()

    process_all(replacements)


if __name__ == '__main__':
    main()
