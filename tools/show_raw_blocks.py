"""
Affiche le contenu brut (avec codes de contrôle) des blocs de dialogue d'un GMD.

Utilisation :
  python3 tools/show_raw_blocks.py <gmd_name> [<filtre>] [--game-dir <path>]

  gmd_name   : nom court du GMD (ex: _sce00_c000_0010_eng)
  filtre     : texte visible à chercher (optionnel, ex: "nervous")
  --game-dir : dossier racine du jeu TGAAC (défaut: chemin Steam standard)

Exemples :
  python3 tools/show_raw_blocks.py _sce00_c000_0010_eng
  python3 tools/show_raw_blocks.py _sce00_c000_0010_eng "nervous"
  python3 tools/show_raw_blocks.py _sce00_c000_0010_eng --game-dir /path/to/TGAAC

Sortie : pour chaque bloc, affiche le contenu brut EN (avec codes) à copier dans le JSON.
"""

import sys
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.gmd_utils import read_gmd, get_strings, _visible
from tools.arc_utils import read_arc


DEFAULT_GAME_DIR = '/home/korphos/.steam/debian-installation/steamapps/common/TGAAC'

# Mapping nom court GMD → chemin ARC relatif dans le dossier jeu
GMD_TO_ARC = {
    '_sce00_c000_0000_eng': 'nativeDX11x64/archive/BB/sce00_eng.arc',
    '_sce00_c000_0010_eng': 'nativeDX11x64/archive/BB/sce00_eng.arc',
    '_sce01_c000_0000_eng': 'nativeDX11x64/archive/BB/sce01_eng.arc',
    # Ajouter d'autres GMD au besoin
}


def main():
    parser = argparse.ArgumentParser(description='Affiche les blocs de dialogue bruts d\'un GMD', add_help=False)
    parser.add_argument('gmd_name', nargs='?')
    parser.add_argument('filtre', nargs='?')
    parser.add_argument('--game-dir', default=DEFAULT_GAME_DIR)
    parser.add_argument('-h', '--help', action='store_true')
    args = parser.parse_args()

    if args.help or not args.gmd_name:
        print(__doc__)
        sys.exit(0 if args.help else 1)

    gmd_name = args.gmd_name
    filtre = args.filtre.lower() if args.filtre else None
    game_dir = Path(args.game_dir)

    arc_rel = GMD_TO_ARC.get(gmd_name)
    if not arc_rel:
        # Cherche dans tous les ARC connus
        for key, val in GMD_TO_ARC.items():
            if gmd_name in key:
                arc_rel = val
                break
    if not arc_rel:
        print(f"GMD inconnu : {gmd_name}")
        print(f"GMD connus : {list(GMD_TO_ARC.keys())}")
        sys.exit(1)

    # Préfère le backup .bak s'il existe
    arc_path = Path(str(game_dir / arc_rel) + '.bak')
    if not arc_path.exists():
        arc_path = game_dir / arc_rel
    if not arc_path.exists():
        print(f"ARC introuvable : {arc_path}")
        print(f"(ni .bak ni original dans {game_dir})")
        sys.exit(1)

    with open(arc_path, 'rb') as f:
        arc_data = f.read()

    entries = read_arc(arc_data)
    gmd_data = next((d for n, d in entries if gmd_name in n), None)
    if gmd_data is None:
        print(f"GMD {gmd_name!r} non trouvé dans {arc_path.name}")
        sys.exit(1)

    gmd = read_gmd(gmd_data)
    strings = get_strings(gmd)

    count = 0
    for si, s in enumerate(strings):
        try:
            text = s.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for m in re.finditer(r'<E025[^>]*>(.*?)(<E023>|<PAGE>)', text, re.DOTALL):
            content = m.group(1)
            vis = _visible(content)
            if not vis or len(vis) < 2:
                continue
            if filtre and filtre not in vis.lower():
                continue
            print(f'[s{si}] vis : {repr(vis[:80])}')
            print(f'      raw : {repr(content)}')
            print()
            count += 1

    print(f'--- {count} blocs affichés ---')


if __name__ == '__main__':
    main()
