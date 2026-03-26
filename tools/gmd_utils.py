"""
Utilitaires pour lire et modifier les fichiers GMD de TGAAC (format MT Framework).

Structure GMD :
  [0:4]   magic "GMD\x00"
  [4:6]   version
  [6:8]   flags
  [8:12]  unk1
  [12:16] file_hash (0 pour les scripts)
  [16:20] unk2
  [20:24] key_count
  [24:28] str_count
  [28:32] key_names_size  (taille du bloc des noms de clés, juste avant str_values)
  [32:36] str_values_size (taille du bloc des valeurs de strings, en fin de fichier)
  [36:40] name_len
  [40:40+name_len] nom du fichier (null-terminated)
  ...
  [-(key_names_size+str_values_size) : -str_values_size] = key_names
  [-str_values_size:]                                     = str_values (strings séparées par \x00)

Pour les GMD de script, les strings sont accédées séquentiellement par index.
Il n'y a pas d'offset table à mettre à jour quand la taille change.
"""

import struct
import re


# ─── Estimation de la largeur du texte (police TGAAC) ─────────────────────────
# Calibré sur : "La vérité, c'est que...je suis si terriblement nerveuse que j'"
# → ~46.75 unités (rentre dans le cadre)
# "j'en" ajoute 2.95 → 48.75 (dépasse) → MAX = 47.5
_CHAR_WIDTHS: dict[str, float] = {
    # Très étroits
    'i': 0.45, 'l': 0.45, '|': 0.45, '!': 0.45,
    ':': 0.45, ';': 0.45, '.': 0.45, ',': 0.45,
    "'": 0.40, '\u2019': 0.40,  # apostrophe droite et typographique
    ' ': 0.40,
    # Étroits
    'j': 0.55, 'r': 0.60, 't': 0.60, 'f': 0.60, '1': 0.55,
    '(': 0.55, ')': 0.55, '[': 0.55, ']': 0.55,
    '"': 0.60, '\u00ab': 0.60, '\u00bb': 0.60,  # «»
    '-': 0.60,
    # Larges
    'm': 1.40, 'w': 1.35, 'M': 1.40, 'W': 1.35,
}
_DEFAULT_CHAR_WIDTH = 1.0
_MAX_LINE_WIDTH = 47.5  # unités ≈ largeur max du cadre de dialogue TGAAC


def estimate_text_width(text: str) -> float:
    """Estime la largeur visuelle d'un texte dans la police de dialogue TGAAC.
    Les codes de contrôle <...> sont ignorés (largeur zéro)."""
    text_clean = re.sub(r'<[^>]+>', '', text)
    return sum(_CHAR_WIDTHS.get(c, _DEFAULT_CHAR_WIDTH) for c in text_clean)


def _split_words(segment: str) -> list[str]:
    """Découpe un segment sur les espaces en traitant les codes <...> comme des
    tokens atomiques (les codes peuvent contenir des espaces, ex: <E003 10>)."""
    words = []
    current = ''
    depth = 0
    for ch in segment:
        if ch == '<':
            depth += 1
            current += ch
        elif ch == '>':
            depth -= 1
            current += ch
        elif ch == ' ' and depth == 0:
            if current:
                words.append(current)
            current = ''
        else:
            current += ch
    if current:
        words.append(current)
    return words


def wrap_dialogue_line(text: str, max_width: float = _MAX_LINE_WIDTH) -> str:
    """
    Ajoute des sauts de ligne (\\n) pour que le texte tienne dans le cadre TGAAC.

    - Si le texte contient déjà des \\n explicites (mis manuellement), chaque
      segment est wrappé indépendamment.
    - Le découpage se fait uniquement aux espaces (les mots ne sont pas coupés).
    - Les codes de contrôle <...> (même multi-mots comme <E003 10>) sont traités
      comme des tokens atomiques de largeur zéro.
    - Les tokens purement ponctuels (?, !, ?!, :, ;, », …) ne peuvent pas
      démarrer une nouvelle ligne — ils restent attachés au mot précédent.
    """
    if not text:
        return text

    # <PAGE> délimite des boîtes séparées — chaque boîte est wrappée indépendamment
    if '<PAGE>' in text:
        return '<PAGE>'.join(wrap_dialogue_line(part, max_width) for part in text.split('<PAGE>'))

    # Tokens qui ne peuvent pas démarrer une ligne (ponctuation en début de mot)
    _PUNCT_START = re.compile(r'^[?!:;»…]+$')

    space_w = _CHAR_WIDTHS.get(' ', _DEFAULT_CHAR_WIDTH)
    result_segments = []

    for segment in text.split('\n'):
        words = _split_words(segment)
        lines: list[str] = []
        current = ''
        current_w = 0.0

        for word in words:
            word_w = estimate_text_width(word)
            if current:
                needed = space_w + word_w
                if current_w + needed > max_width and not _PUNCT_START.match(word):
                    lines.append(current)
                    current = word
                    current_w = word_w
                else:
                    current += ' ' + word
                    current_w += needed
            else:
                current = word
                current_w = word_w

        if current:
            lines.append(current)

        result_segments.append('\n'.join(lines))

    return '\n'.join(result_segments)


def read_gmd(data: bytes) -> dict:
    """Parse un fichier GMD et retourne un dict avec ses composants."""
    assert data[:4] == b'GMD\x00', f"Magic invalide: {data[:4]!r}"
    key_names_size = struct.unpack_from('<I', data, 28)[0]
    str_values_size = struct.unpack_from('<I', data, 32)[0]
    name_len = struct.unpack_from('<I', data, 36)[0]

    str_values_start = len(data) - str_values_size
    key_names_start = str_values_start - key_names_size
    header_end = 40 + name_len  # approximatif, le vrai est key_names_start

    return {
        'header': data[:key_names_start],           # header + key entry table
        'key_names': data[key_names_start:str_values_start],
        'str_values_raw': data[str_values_start:],
        'str_values_size': str_values_size,
        'key_names_size': key_names_size,
    }


def get_strings(gmd: dict) -> list[bytes]:
    """Retourne la liste des strings de la section str_values."""
    parts = gmd['str_values_raw'].split(b'\x00')
    # Le dernier élément est toujours vide (null terminal final)
    return parts[:-1] if parts and parts[-1] == b'' else parts


def set_strings(gmd: dict, strings: list[bytes]) -> bytes:
    """
    Reconstruit le fichier GMD avec la nouvelle liste de strings.
    Met à jour str_values_size dans le header.
    Retourne les bytes du fichier GMD modifié.
    """
    new_str_values = b'\x00'.join(strings) + b'\x00'
    new_size = len(new_str_values)

    # Met à jour str_values_size dans le header (offset 32)
    header = bytearray(gmd['header'])
    struct.pack_into('<I', header, 32, new_size)

    return bytes(header) + gmd['key_names'] + new_str_values


def _visible(segment: str) -> str:
    """Extrait le texte visible d'un segment GMD (supprime tous les codes <...>)."""
    return re.sub(r'<[^>]+>', '', segment).replace('\r\n', '\n').replace('\n', ' ').strip()


def translate_string(s: bytes, replacements: dict[str, str],
                     strat4_log: list[str] | None = None) -> bytes:
    """
    Applique les remplacements texte dans une string de script GMD.
    Les clés de replacements sont soit le contenu brut EN (priorité), soit le
    texte visible EN (fallback pour stratégie 4).

    Stratégies (en cascade) :
    1. Correspondance exacte dans le texte brut
    2. Normalisation CRLF→LF puis correspondance
    3. Correspondance flexible : autorise <codes> et blancs entre mots
       (clés visibles seulement — les clés brutes contenant < sont ignorées)
    4. Correspondance par texte visible des blocs <E025>…<E023/PAGE> :
       dernier recours ; émet un warning via strat4_log si activé.
       Si le FR contient <PAGE>, insère l'opener <E025 N> après chaque <PAGE>.
    """
    try:
        text = s.decode('utf-8')
    except UnicodeDecodeError:
        return s  # binary, on ne touche pas

    # Stratégies 1–3 : remplacement direct dans le texte brut
    # On applique les clés les plus longues en premier pour éviter qu'une clé courte
    # transforme partiellement le texte et empêche le match d'une clé plus longue.
    for en, fr in sorted(replacements.items(), key=lambda x: -len(x[0])):
        if not en:
            continue

        # 1. Correspondance exacte
        if en in text:
            text = text.replace(en, fr)
            continue

        # 2. CRLF → LF normalisé
        en_lf = en.replace('\r\n', '\n')
        text_lf = text.replace('\r\n', '\n')
        if en_lf in text_lf:
            text = text_lf.replace(en_lf, fr).replace('\n', '\r\n')
            continue

        # 3. Flexible : autorise <codes> et blancs entre mots
        # Ignoré pour les clés brutes (contenant <) — elles sont pour stratégie 1/2
        # Le SEP n'autorise PAS <E023> ni <PAGE> pour ne pas franchir les boîtes
        words = en_lf.split()
        if len(words) >= 2 and '<' not in en:
            SEP = r'(?:(?:<(?!E023|/?PAGE)[^>]+>|\s)*)'
            pattern = SEP.join(re.escape(w) for w in words)
            try:
                m = re.search(pattern, text_lf, re.DOTALL)
                if m:
                    new_lf = text_lf[:m.start()] + fr + text_lf[m.end():]
                    text = new_lf.replace('\n', '\r\n')
            except re.error:
                pass

    # Stratégie 4 : correspondance par texte visible des blocs <E025>…<E023/PAGE>
    # Dernier recours — ne devrait pas arriver si les clés brutes sont correctes.
    # Émet un warning via strat4_log quand elle est utilisée.
    # Si le FR contient <PAGE> : insère l'opener <E025 N> après chaque <PAGE>
    #   pour créer une nouvelle boîte de dialogue.
    def _replace_segment(m: re.Match) -> str:
        opener = m.group(1)   # <E025 N>
        content = m.group(2)  # tout ce qui est entre <E025> et <E023/PAGE>
        closer = m.group(3)   # <E023> ou <PAGE>
        vis = _visible(content)
        # Cherche dans le dict en normalisant les espaces multiples
        vis_norm = re.sub(r'\s+', ' ', vis)
        for en, fr in replacements.items():
            en_norm = re.sub(r'\s+', ' ', en.replace('\r\n', ' ').replace('\n', ' '))
            if en_norm == vis_norm:
                if '<' in fr:
                    # FR avec codes — utilisé directement, <PAGE> crée une nouvelle boîte
                    if '<PAGE>' in fr:
                        parts = fr.split('<PAGE>')
                        return opener + ('<PAGE>' + opener).join(parts) + closer
                    return opener + fr + closer
                else:
                    # FR sans codes : remplacement sûr seulement si le contenu
                    # original n'a lui-même aucun code (sinon on perdrait des codes)
                    if re.search(r'<[^>]+>', content):
                        if strat4_log is not None:
                            strat4_log.append(vis_norm + '  ← UNSAFE: FR sans codes mais EN a des codes, original préservé')
                        return m.group(0)  # original préservé intact
                    return opener + fr + closer
        return m.group(0)  # pas de match : laisse intact

    text = re.sub(
        r'(<E025[^>]*>)(.*?)(<E023>|<PAGE>|<E027>)',
        _replace_segment,
        text,
        flags=re.DOTALL
    )

    return text.encode('utf-8')


def extract_dialogue_lines(strings: list[bytes]) -> list[tuple[int, int, str]]:
    """
    Extrait toutes les lignes de dialogue visibles.
    Retourne une liste de (string_idx, line_idx_in_string, texte_visible).
    """
    results = []
    for si, s in enumerate(strings):
        try:
            text = s.decode('utf-8')
        except UnicodeDecodeError:
            continue
        matches = list(re.finditer(r'<E025 \d+>(.*?)(?=<E023>|<PAGE>)', text, re.DOTALL))
        for li, m in enumerate(matches):
            visible = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            visible = visible.replace('\r\n', '\n').strip()
            if visible and len(visible) > 1:
                results.append((si, li, visible))
    return results
