"""
Applique la même correction de RUBY annotations (texte jaune) aux fichiers
legacy (bsdiffs) qu'aux JSON DGS1 — en réutilisant la logique de fix_dgs1_ruby.py.

Usage :
  python3 tools/fix_legacy_ruby.py
"""

import json
import struct
import sys
from pathlib import Path

import bsdiff4

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.fix_dgs1_ruby import process_fr_field
from tools.gmd_utils import read_gmd, get_strings, set_strings
from tools.arc_utils import read_arc, write_arc

REPO    = Path(__file__).parent.parent
GAME    = Path('/home/korphos/.steam/debian-installation/steamapps/common/TGAAC')
PATCHES = REPO / 'assets' / 'patches'
LEGACY  = REPO / 'traductions' / 'legacy'


def fix_gmd_bytes(gmd_bytes: bytes) -> tuple[bytes, int]:
    gmd = read_gmd(gmd_bytes)
    strings = get_strings(gmd)
    stats = {'total': 0, 'kept_rb': 0, 'used_rt': 0, 'examples': []}
    new_strings = []
    for s in strings:
        try:
            text = s.decode('utf-8')
        except UnicodeDecodeError:
            new_strings.append(s)
            continue
        fixed = process_fr_field(text, stats)
        new_strings.append(fixed.encode('utf-8'))
    return set_strings(gmd, new_strings), stats['total']


def fix_arc_bytes(arc_bytes: bytes) -> tuple[bytes, int]:
    entries = read_arc(arc_bytes)
    new_entries = []
    total = 0
    for name, raw in entries:
        if raw[:4] == b'GMD\x00':
            fixed_raw, n = fix_gmd_bytes(raw)
            new_entries.append((name, fixed_raw))
            total += n
        else:
            new_entries.append((name, raw))
    first_offset = struct.unpack_from('<I', arc_bytes, 8 + 140)[0]
    return write_arc(new_entries, arc_bytes[:8], data_start=first_offset), total


def update_legacy_json(json_path: Path) -> int:
    if not json_path.exists():
        return 0
    data = json.loads(json_path.read_text(encoding='utf-8'))
    stats = {'total': 0, 'kept_rb': 0, 'used_rt': 0, 'examples': []}
    for entries in data.values():
        for e in entries:
            if 'fr' in e:
                e['fr'] = process_fr_field(e['fr'], stats)
    if stats['total']:
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding='utf-8')
    return stats['total']


def main() -> None:
    manifest = json.loads((PATCHES / 'manifest.json').read_text(encoding='utf-8'))
    print('=== Correction RUBY/texte jaune dans les fichiers legacy ===\n')
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
            # Les ARCs sont compressés — on ne peut pas tester les bytes bruts
            fixed_bytes, n = fix_arc_bytes(fr_bytes)
        elif rel.endswith('.gmd'):
            # Pour les GMDs directs, le test rapide suffit
            if b'<RUBY>' not in fr_bytes:
                continue
            fixed_bytes, n = fix_gmd_bytes(fr_bytes)
        else:
            continue

        if n == 0:
            continue

        new_patch = bsdiff4.diff(orig_bytes, fixed_bytes)
        bsdiff_path.write_bytes(new_patch)
        manifest[rel]['bsdiff_size'] = len(new_patch)

        rel_clean = rel
        if rel_clean.startswith('nativeDX11x64/'):
            rel_clean = rel_clean[len('nativeDX11x64/'):]
        stem = rel_clean.rsplit('.', 1)[0]
        update_legacy_json(LEGACY / (stem + '.json'))

        print(f'  ✓ {rel.split("/")[-1]:45} {n} bloc(s) RUBY corrigé(s)')
        total_files += 1

    (PATCHES / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'\n{total_files} fichier(s) modifié(s).')


if __name__ == '__main__':
    main()
