#!/usr/bin/env python3
"""
fix_dgs1_ruby.py — Replace RUBY annotation patterns in DGS1 translation JSON files.

Processes sce00.json through sce04.json, replacing RUBY blocks with their
French (or English-kept) text, removing Japanese text and yellow annotations.
"""

import json
import re
import os

# ---------------------------------------------------------------------------
# Character map: game-specific fullwidth-adjacent chars → French/Latin
# ---------------------------------------------------------------------------
CHAR_MAP = {
    '\uFFC0': 'à',
    '\uFFC2': 'â',
    '\uFFC7': 'ç',
    '\uFFC8': 'è',
    '\uFFC9': 'é',
    '\uFFCA': 'ê',
    '\uFFCE': 'î',
    '\uFFCF': 'ï',
    '\uFFD4': 'ô',
    '\uFFDB': 'û',
}

# Words to keep as English (give British atmosphere feel)
KEEP_AS_IS = {
    'lady', 'ladies', 'lord', 'lords', 'sir', 'sorry',
    'hello', 'goodbye', 'my lady', 'my lord', 'miss'
}


def normalize_rt(rt_raw: str) -> str:
    """
    Normalize the RT content:
    1. Strip COL tags
    2. Convert fullwidth chars U+FF01-U+FF5E to ASCII (subtract 0xFEE0)
    3. Map game-specific chars via CHAR_MAP
    4. Drop other chars with code point > 0x2E7F (CJK, Hangul, etc.)
    5. Normalize spaces
    """
    # Strip COL tags (and any other tags)
    text = re.sub(r'<[^>]+>', '', rt_raw)

    result = []
    for ch in text:
        cp = ord(ch)
        # Game-specific map
        if ch in CHAR_MAP:
            result.append(CHAR_MAP[ch])
        # Fullwidth ASCII range U+FF01–U+FF5E → ASCII
        elif 0xFF01 <= cp <= 0xFF5E:
            result.append(chr(cp - 0xFEE0))
        # Fullwidth space U+3000 → regular space
        elif cp == 0x3000:
            result.append(' ')
        # Drop high code points (CJK, Hangul, other non-Latin)
        elif cp > 0x2E7F:
            pass  # drop
        else:
            result.append(ch)

    normalized = ''.join(result)
    # Normalize multiple spaces to single space, strip leading/trailing
    normalized = re.sub(r' {2,}', ' ', normalized).strip()
    return normalized


def choose_replacement(rb_raw: str, rt_normalized: str) -> str:
    """
    Decide whether to use RB text (keep as-is) or RT text (French translation).
    """
    rb = re.sub(r'<[^>]+>', '', rb_raw).strip().strip('"\'').strip()
    rt = rt_normalized.strip()

    # If RB is Japanese → use RT
    if re.search(r'[\u3000-\u9fff]', rb):
        return rt if rt else rb

    rb_lower = rb.lower()

    # Well-known English words to keep as-is (give British feel)
    if rb_lower in KEEP_AS_IS:
        return rb

    # If RB has French accented chars AND RT has English patterns → keep RB (reversed case)
    rb_has_accent = bool(re.search(r'[àâçèéêëîïôûùüÿ]', rb))
    if rb_has_accent:
        # RT is English (has English articles/words) → keep French RB
        if rt and re.search(
            r'\b(the|my|his|her|your|our|its|their|this|that|these|those|at |of |for |with |by |from )\b',
            rt, re.I
        ):
            return rb
        # RT is empty or also French → use RT
        return rt if rt else rb

    # If RB has French function words → likely French phrase, check if RT is English
    if re.search(
        r'\b(le|la|les|un|une|des|du|de|ma|mon|mes|sa|son|ses|ce|cette|au|aux|pour|dans|avec|sans|en|je|tu|il|elle|nous|vous|ils|elles|et|ou)\b',
        rb, re.I
    ):
        # RT is English → keep RB
        if rt and re.search(
            r'\b(the|my|his|her|your|our|its|their|this|that|these|those|at the|of the)\b',
            rt, re.I
        ):
            return rb
        return rt if rt else rb

    # RT contains KEEP_AS_IS words → RT has English feel → use RB
    if rt and re.search(r'\b(' + '|'.join(KEEP_AS_IS) + r')\b', rt, re.I):
        return rb

    # Default: use RT (English→French translation or Japanese→French)
    return rt if rt else rb


# Regex for RUBY blocks.
# Covers:
#   - Optional prefix tag: <E507 ...>, <E516 ...>, <E517 ...>, or bare RUBY
#   - Optional whitespace/newline between prefix and <RUBY>
#   - Optional trailing <E519>
RUBY_PATTERN = re.compile(
    r'(?:<(?:E516|E507|E517)[^>]*>\s*)?<RUBY><RB>(.*?)</RB><RT>(.*?)</RT></RUBY>\s*(?:<E519>)?',
    re.DOTALL
)

# Regex to remove remaining Japanese characters outside tags
JP_RANGE = re.compile(r'[\u3000-\u9fff]')


def remove_japanese_outside_tags(text: str) -> str:
    """Remove Japanese characters that appear outside of XML/game tags."""
    result = []
    i = 0
    while i < len(text):
        if text[i] == '<':
            # Find end of tag
            end = text.find('>', i)
            if end == -1:
                result.append(text[i:])
                break
            result.append(text[i:end + 1])
            i = end + 1
        else:
            ch = text[i]
            if JP_RANGE.match(ch):
                pass  # drop
            else:
                result.append(ch)
            i += 1
    return ''.join(result)


def process_fr_field(fr: str, stats: dict) -> str:
    """
    Process a single fr field: replace RUBY blocks, then clean up residual JP.
    Updates stats dict in place.
    """
    def replacer(m):
        rb_raw = m.group(1)
        rt_raw = m.group(2)
        rt_norm = normalize_rt(rt_raw)
        replacement = choose_replacement(rb_raw, rt_norm)

        rb_clean = re.sub(r'<[^>]+>', '', rb_raw).strip()

        stats['total'] += 1
        if replacement == rb_clean or replacement == rb_raw.strip():
            stats['kept_rb'] += 1
        else:
            stats['used_rt'] += 1

        # Record examples for reporting
        if len(stats['examples']) < 20:
            stats['examples'].append({
                'before': m.group(0),
                'rb_raw': rb_raw,
                'rt_norm': rt_norm,
                'replacement': replacement,
            })

        return replacement

    processed = RUBY_PATTERN.sub(replacer, fr)

    # Safety cleanup: remove any remaining Japanese chars outside tags
    if JP_RANGE.search(processed):
        processed = remove_japanese_outside_tags(processed)

    return processed


def process_file(filepath: str) -> dict:
    """Load, process, and save a JSON file. Returns per-file stats."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    stats = {'total': 0, 'kept_rb': 0, 'used_rt': 0, 'examples': []}

    for key, entries in data.items():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            if 'fr' not in item:
                continue
            fr = item['fr']
            if not isinstance(fr, str):
                continue
            new_fr = process_fr_field(fr, stats)
            if new_fr != fr:
                item['fr'] = new_fr

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return stats


def main():
    base_dir = '/home/korphos/dev/DGS-FR/traductions/dgs1'
    files = [f'sce0{i}.json' for i in range(5)]

    grand_total = 0
    grand_kept = 0
    grand_rt = 0

    for filename in files:
        filepath = os.path.join(base_dir, filename)
        if not os.path.exists(filepath):
            print(f'  [SKIP] {filename} not found')
            continue

        stats = process_file(filepath)
        print(f'\n=== {filename} ===')
        print(f'  RUBY blocks processed : {stats["total"]}')
        print(f'  Kept RB (as-is)       : {stats["kept_rb"]}')
        print(f'  Used RT (translation) : {stats["used_rt"]}')

        grand_total += stats['total']
        grand_kept  += stats['kept_rb']
        grand_rt    += stats['used_rt']

        # Print examples for sce00 only
        if filename == 'sce00.json':
            print(f'\n  --- 10 example transformations (sce00) ---')
            for i, ex in enumerate(stats['examples'][:10], 1):
                print(f'\n  [{i}] BEFORE: {repr(ex["before"][:120])}')
                print(f'       RB raw : {repr(ex["rb_raw"].strip())}')
                print(f'       RT norm: {repr(ex["rt_norm"])}')
                print(f'       AFTER  : {repr(ex["replacement"])}')

    print(f'\n=== GRAND TOTAL ===')
    print(f'  RUBY blocks processed : {grand_total}')
    print(f'  Kept RB (as-is)       : {grand_kept}')
    print(f'  Used RT (translation) : {grand_rt}')


if __name__ == '__main__':
    main()
