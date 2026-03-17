# Recherche Technique - Traduction DGS2 (TGAAC Steam)

## Documents de référence

- **Ce fichier** : pipeline technique, formats ARC/GMD, conventions de traduction, pièges connus
- **[TGAAC_STORY_CONTEXT.md](TGAAC_STORY_CONTEXT.md)** : contexte narratif complet (spoilers), personnages, vocabulaire cohérent — **à lire avant de traduire**

---

## État actuel du projet

- DGS1 (GO/) : **entièrement traduit** en français, patch Steam fonctionnel
- DGS2 (BB/) : **traduction en cours**
  - `sce00_c000.json` : prologue cinématique + antichambre du tribunal (Épisode 1, intro) — **terminé et fonctionnel**
  - Tout le reste : à faire

### Commandes pour régénérer et appliquer le patch DGS2

```bash
# 1. Régénérer le patch
python3 tools/create_patch_dgs2.py \
    --game-dir /home/korphos/.steam/debian-installation/steamapps/common/TGAAC \
    --output dgs2_fr_test.aapatch

# 2. Appliquer le patch (Python direct, sans l'UI)
python3 -c "
import sys, shutil
sys.path.insert(0, '/home/korphos/dev/DGS-FR')
import src.aapatch as aapatch

game_dir = '/home/korphos/.steam/debian-installation/steamapps/common/TGAAC'
target   = game_dir + '/nativeDX11x64/archive/BB/sce00_eng.arc'
backup   = target + '.bak'
patch_path = '/home/korphos/dev/DGS-FR/dgs2_fr_test.aapatch'

shutil.copy2(backup, target)   # OBLIGATOIRE : restaure l'original avant patch
p = aapatch.AAPatch()
p.read(patch_path)
p.patch_all(game_dir, flags=[2])
print('Patch appliqué.')
"
```

> ⚠️ **Ne jamais lancer `main.py`** pour appliquer le patch DGS2 — ça ouvre une GUI inutile.
> ⚠️ **Toujours restaurer le backup avant d'appliquer** : `patch_all` vérifie le hash du fichier original. Le `.bak` est créé automatiquement lors de la première génération du patch.

---

## Structure du jeu Steam

Installation : `/home/korphos/.steam/debian-installation/steamapps/common/TGAAC/`

```
nativeDX11x64/
├── GO/          ← DGS1 (traduit)
│   ├── msg/     ← fichiers .gmd bruts (items, UI)
│   ├── script/output/  ← scripts de scène bruts
│   └── scene/
├── BB/          ← DGS2 (en cours de traduction)
│   ├── msg/     ← fichiers .gmd bruts
│   ├── script/output/  ← macros + system
│   └── scene/
└── archive/
    ├── GO/      ← archives .arc DGS1
    └── BB/      ← archives .arc DGS2 (dialogue principal ici)
```

**Les textes sont en anglais** (version localisation anglaise).

---

## Format des fichiers .arc

Magic : `ARC\x00`, version `07 00`

```
Header (8 bytes):
  [0:4]  magic = "ARC\x00"
  [4:6]  version (little-endian)
  [6:8]  nb_entries (little-endian)

Index : nb_entries × 144 bytes :
  [0:128]   filename (null-padded, chemin Windows ex: "BB\script\output\_sce00_c000_0010_eng")
  [128:132] ext_hash (0x242bb29a pour .gmd)
  [132:136] compressed_size (zlib)
  [136:140] decompressed_size | 0x40000000 (flag)
  [140:144] absolute_offset dans le fichier

Data section : alignée à 0x8000, chaque entrée = zlib.compress(gmd_data, level=6)
```

Outils : `tools/arc_utils.py` — fonctions `read_arc()` et `write_arc()`.

---

## Format des fichiers .gmd

Magic : `GMD\x00`

```
[0:4]   magic "GMD\x00"
[4:8]   version + flags
[8:12]  unk1
[12:16] file_hash
[16:20] unk2
[20:24] key_count
[24:28] str_count
[28:32] key_names_size
[32:36] str_values_size  ← à mettre à jour si les strings changent de taille
[36:40] name_len
[40:40+name_len] nom du fichier (null-terminated)
...
[-(key_names_size+str_values_size) : -str_values_size] = key_names
[-str_values_size:]  = str_values (strings séparées par \x00)
```

**Important :** il n'y a pas d'offset table à mettre à jour. Les strings script sont accédées séquentiellement par index. Seul `str_values_size` (offset 32) doit être mis à jour.

Outils : `tools/gmd_utils.py` — fonctions `read_gmd()`, `get_strings()`, `set_strings()`, `translate_string()`.

---

## Codes de contrôle GMD (codes inline dans les strings)

| Code | Rôle |
|---|---|
| `<E025 N>` | Début d'un segment de dialogue (N = vitesse d'affichage) |
| `<E023>` | Fin de segment |
| `<PAGE>` | Saut de page (nouveau segment visible) |
| `<E003 N>` | Pause (N = durée en frames) |
| `<CNTR>` | Centrage du texte |
| `<E007>` | **Couleur bleue** (pensées intérieures, monologues) |
| `<E006>` | **Début surligné orange** (mot mis en évidence) |
| `<E005>` | **Fin de surligné orange** → retour couleur normale (blanc) |
| `<E007>` (après E006) | **Fin de surligné orange** → retour couleur bleue (dans bulle de pensée) |
| `<E341>` | Italique |
| `<E330>` | Autre style (fade, accent) |
| `<E238>` | Style spécial |
| `<E346>` | Style voix |
| `<RDFG N>` | Identifiant de ligne (système de patch) |
| `<E800 N>` | Checkpoint (animation/événement) |
| `<E049>` | Pause courte intercalée |
| `<E089 N M>` | Effet vocal |

### Règle d'utilisation des codes couleur

- **Bulle de pensée** : le bloc commence par `<E025 N><E007>(texte...)`. Le `<E007>` en tête = tout le bloc en bleu.
  - Pour un mot orange dans une bulle bleue : `<E006>mot<E007>` (le `<E007>` remet en bleu)
- **Dialogue normal** (blanc) : pour un mot orange : `<E006>mot<E005>`

---

## Pipeline de traduction — comment ça fonctionne

### 1. Fichier de traduction JSON

Format : `traductions/dgs2/<scene>.json`

```json
{
  "_sce00_c000_0010_eng": [
    {
      "id": "002",
      "en": "<E007>(Here I am again after nine months...<E003 12>\r\n<E025 2>The Supreme Court of Judicature of Japan.)",
      "fr": "<E007>(Me voilà de retour après neuf mois...<E003 12>\r\n<E025 2>La Cour Suprême de Judicature du Japon.)"
    }
  ]
}
```

**Conventions importantes :**
- `"en"` = contenu brut du bloc `<E025>…<E023/PAGE>` en anglais (avec TOUS les codes)
- `"fr"` = traduction avec les codes **placés manuellement** aux positions sémantiquement équivalentes
- **Sauts de ligne automatiques** — `wrap_dialogue_line()` est toujours appliqué, même si `"fr"` contient des codes. Le traducteur n'a pas besoin de gérer les retours à la ligne.
- **Maximum 2 lignes par boîte** — un `⚠ DÉPASSEMENT` est émis si c'est dépassé
- **Créer une 2ème boîte** : écrire `<PAGE>` dans `"fr"` à l'endroit voulu — le script injecte automatiquement l'opener `<E025 N>` après chaque `<PAGE>`
- Les entrées où EN visible == FR visible sont ignorées (honorifiques, `...`, noms propres identiques)

**Pour obtenir le raw EN d'une entrée :**
```bash
python3 tools/show_raw_blocks.py _sce00_c000_0010_eng "mot clé"
```

**Warning à la génération du patch :**
Si un code présent dans `"en"` est absent de `"fr"` → `⚠ CODES MANQUANTS [gmd #id]: <code>` affiché. Corriger avant de finaliser.

### 2. Détection et application des traductions

`tools/create_patch_dgs2.py` :
1. Lit le JSON → construit `dict[en_brut → fr_text]` + `dict[en_visible → fr_text]` (double clé)
2. Pour chaque GMD dans l'ARC : appelle `translate_string(s, replacements)` sur chaque string
3. Avertit (`⚠ NON TRADUIT`) si un bloc anglais connu reste non traduit après patch

`translate_string()` dans `tools/gmd_utils.py` utilise 4 stratégies en cascade :

| Stratégie | Description | Cas d'usage |
|---|---|---|
| 1 | Correspondance exacte dans le texte brut | Prioritaire — matche via la clé brute `en_raw` |
| 2 | Normalisation CRLF→LF puis match | Différences `\r\n` vs `\n` |
| 3 | Regex flexible entre les mots (clés visibles seulement, **pas** `<E023>`/`<PAGE>`) | Fallback texte visible sans codes intercalés |
| 4 | Correspondance sur le texte visible du bloc `<E025>...<E023/PAGE>` | Dernier recours — **ne devrait jamais arriver** si `en_raw` est correct |

**Stratégie 4 — dernier recours :**
- Grâce à la double clé (`en_raw` + `en_visible`), la stratégie 1 matche directement pour presque tous les cas — la stratégie 4 ne devrait jamais être nécessaire
- Si elle se déclenche quand même → `⚠ STRATÉGIE 4` est affiché : vérifier que le champ `"en"` correspond exactement au contenu brut du GMD
- En cas de match : utilise `fr` directement si `'<' in fr` ; si `'<' not in fr` mais que le bloc original contient des codes → **ne remplace pas** (préserve l'original) et émet un warning
- Si `fr` contient `<PAGE>` : insère automatiquement l'opener `<E025 N>` après chaque `<PAGE>` pour créer une nouvelle boîte

---

## Règles de mise en page — à respecter impérativement

### Largeur de ligne

La police de dialogue TGAAC a une largeur max calibrée à **47.5 unités**. La fonction `wrap_dialogue_line()` calcule automatiquement les sauts nécessaires.

Table des largeurs (extraite de `gmd_utils.py`) :
- Caractères très étroits (i, l, !, :, ;, ., ,, ', espace) : 0.40–0.45
- Caractères étroits (j, r, t, f, 1, (, )) : 0.55–0.60
- Caractères larges (m, w, M, W) : 1.35–1.40
- Tous les autres : 1.0 par défaut
- **Les codes `<...>` sont ignorés** dans le calcul de largeur (largeur zéro)

### Ponctuation française

La ponctuation de fin ` ?`, ` !`, ` :`, ` ;`, ` »`, ` ?!` comprend une espace insécable en français. Ces tokens ne peuvent pas démarrer une nouvelle ligne — `wrap_dialogue_line()` les attache toujours au mot précédent.

### Limite de 2 lignes par boîte

Chaque boîte de dialogue (bloc `<E025>...<E023>` ou `<E025>...<PAGE>`) ne peut afficher que **2 lignes**. Si la traduction en nécessite plus :
- Insérer `<PAGE>` dans `"fr"` pour créer une 2ème boîte (l'opener `<E025 N>` est injecté automatiquement) — à préférer si raccourcir ferait perdre du sens
- Raccourcir/reformuler le texte français si la version courte est suffisamment fidèle

Le script émet `⚠ DÉPASSEMENT` si une boîte dépasse 2 lignes après wrap automatique.

---

## Pièges connus — erreurs à ne pas reproduire

### 1. Codes dans `"en"` absents de `"fr"`

Si un code présent dans `"en"` est absent de `"fr"` → `⚠ CODES MANQUANTS` à la génération. **Toujours corriger avant de finaliser.** Le traducteur doit placer TOUS les codes du bloc EN dans le FR aux positions sémantiquement équivalentes.

La stratégie 4 ne remplace pas si `"fr"` a des codes manquants ET le bloc original en a (préserve l'anglais). L'entrée reste en anglais jusqu'à correction.

### 2. Codes sémantiques — placement

Placer les codes à l'emplacement sémantiquement équivalent, **pas** par proportion mécanique. Exemple : `"Ah good,<E003 8> you're here"` → `"Ah,<E003 8> vous voilà"` (la pause est après "Ah," dans les deux cas, pas après le 2ème mot).

### 3. Stratégie 3 et les frontières de PAGE

La stratégie 3 (regex flexible) ne traverse pas `<E023>` ni `<PAGE>`. Si elle le faisait, elle fusionnerait plusieurs boîtes en une seule (3 lignes, débordement). Le SEP est `r'(?:(?:<(?!E023|/?PAGE)[^>]+>|\s)*)'`.

### 4. Backup obligatoire

Le script utilise **toujours** `.arc_backups/sce00_eng.arc` comme source originale (jamais le fichier jeu qui peut être déjà patché). La restauration du backup avant `patch_all` est obligatoire car `patch_all` vérifie le hash.

---

## Mapping ARC → fichiers JSON

| ARC (dans `nativeDX11x64/archive/BB/`) | GMD concernés | Fichier JSON | État |
|---|---|---|---|
| `sce00_eng.arc` | `_sce00_c000_0000_eng`, `_sce00_c000_0010_eng` | `traductions/dgs2/sce00_c000.json` | ✓ Fait |
| `sce00_eng.arc` | reste des GMD (c001–c009, evidence, etc.) | à créer | |
| `sce01_eng.arc` | ~150 GMD | à créer | |
| `sce02_eng.arc` | ~219 GMD | à créer | |
| `sce03_eng.arc` | ~188 GMD | à créer | |
| `sce04_eng.arc` | ~111 GMD | à créer | |

Pour ajouter une nouvelle scène, éditer `ARC_FILES` et `TRANSLATION_MAP` dans `create_patch_dgs2.py`.

---

## Volume de texte DGS2

| Fichier arc       | Lignes dialogue | Fichiers GMD |
|-------------------|-----------------|--------------|
| sce00_eng.arc     | 3 137           | 59           |
| sce01_eng.arc     | 7 039           | 150          |
| sce02_eng.arc     | 10 374          | 219          |
| sce03_eng.arc     | 7 822           | 188          |
| sce04_eng.arc     | 6 672           | 111          |
| **Total**         | **~35 044**     | **727**      |

---

## Structure des outils

```
tools/
├── gmd_utils.py       ← lecture/écriture GMD, wrap, translate_string (4 stratégies)
├── arc_utils.py       ← lecture/écriture ARC (zlib, index 144 bytes)
└── create_patch_dgs2.py ← pipeline complet : JSON → ARC patché → .aapatch

src/
└── aapatch.py         ← format .aapatch, patch_all (hash + bsdiff4)

traductions/
└── dgs2/
    └── sce00_c000.json  ← traductions Épisode 1 intro (148 entrées)

(dans le dossier jeu, créé automatiquement à la première génération du patch)
nativeDX11x64/archive/BB/sce00_eng.arc.bak  ← backup original Steam
```

---

## Exemple de workflow pour traduire une nouvelle scène

1. **Extraire les GMD** d'un ARC et lister les dialogues :
```python
import sys, re
sys.path.insert(0, '/home/korphos/dev/DGS-FR')
from tools.arc_utils import read_arc
from tools.gmd_utils import read_gmd, get_strings, extract_dialogue_lines

with open('.arc_backups/sce01_eng.arc', 'rb') as f:
    arc_data = f.read()
entries = read_arc(arc_data)

# Lister les dialogues d'un GMD spécifique
for name, raw in entries:
    if '_sce01_c000_0000_eng' in name:
        gmd = read_gmd(raw)
        strings = get_strings(gmd)
        for si, li, text in extract_dialogue_lines(strings):
            print(f'[{si},{li}] {text}')
```

2. **Créer un fichier JSON** `traductions/dgs2/sce01_c000.json` au format `{ "_gmd_name": [ {id, en, fr}, ... ] }`.

3. **Ajouter l'entrée** dans `create_patch_dgs2.py` :
```python
ARC_FILES = {
    'sce00': 'nativeDX11x64/archive/BB/sce00_eng.arc',
    'sce01': 'nativeDX11x64/archive/BB/sce01_eng.arc',  # nouveau
}
TRANSLATION_MAP = {
    'sce01': {
        'BB\\script\\output\\_sce01_c000_0000_eng': 'traductions/dgs2/sce01_c000.json',
    }
}
```

4. Régénérer et appliquer le patch (voir commandes en haut du document).
