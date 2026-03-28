# Recherche Technique - Traduction TGAAC (DGS1 + DGS2, Steam)

## Documents de référence

- **Ce fichier** : pipeline technique, formats ARC/GMD, conventions de traduction, pièges connus
- **[TGAAC_STORY_CONTEXT.md](TGAAC_STORY_CONTEXT.md)** : contexte narratif complet (spoilers), personnages, vocabulaire cohérent — **à lire avant de traduire**

---

## État actuel du projet

- DGS1 (GO/) : **entièrement traduit** en français — traductions extraites en JSON dans `traductions/dgs1/`
- DGS2 (BB/) : **traduction en cours**
  - `sce00_c000.json` : prologue cinématique + antichambre du tribunal (Épisode 1, intro) — **terminé et fonctionnel**
  - Tout le reste : à faire

### Commande unique pour régénérer et appliquer tout le patch

```bash
python3 rebuild_and_apply.py
```

Ce script fait tout en une passe :
1. Applique les assets binaires pré-extraits (polices, UI, textures, sons) depuis `assets/patches/`
2. Régénère `tgaac_fr.aapatch` depuis les JSON (`traductions/dgs1/` + `traductions/dgs2/`)
3. Applique le patch de scènes sur les fichiers du jeu

> ⚠️ **Ne jamais lancer `main.py`** — ça ouvre une GUI inutile.
> ⚠️ Les backups `.arc.bak` sont créés automatiquement à côté des fichiers du jeu lors du premier lancement.

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

Data section : alignée à 0x8000 (ou 0x10000 pour les ARCs avec >227 entrées), chaque entrée = zlib.compress(gmd_data, level=6)
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

Format commun DGS1 et DGS2 : `{ "short_gmd_name": [ {id, en, fr}, ... ] }`

#### Format DGS2 — string de dialogue (bloc `<E025>`)

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

- `"en"` = contenu brut du bloc `<E025>…<E023/PAGE>` (avec tous les codes)
- `"fr"` = traduction avec codes positionnés manuellement
- `wrap_dialogue_line()` est appliqué automatiquement

#### Format DGS1 — bloc individuel `<E025>`

La majorité des entrées DGS1 sont maintenant au format court (un bloc = une entrée) :

```json
{
  "_sce00_c001_0000_eng": [
    {
      "id": "003",
      "en": "<E025 3>If I may...?<E023>",
      "fr": "<E025 4>Ahem, excusez-moi, jeune homme... ?<E023>"
    }
  ]
}
```

- `"en"` = **un seul bloc** `<E025 N>text<E023>` (peut contenir `<PAGE>` pour blocs multi-pages)
- `"fr"` = déjà formaté (extrait du patch original) — **pas de `wrap_dialogue_line()`**
- Détection automatique : `('<E023>' in en_raw or '<E027>' in en_raw) and '<RDFG ' not in en_raw`
- La stratégie 1 cherche ce sous-string dans la grande string GMD et le remplace

**Cas spécial — blocs `<E027>` (monologue jury) :**
Les examens de jury utilisent `<E025 N>...<E027>` au lieu de `<E025 N>...<E023>`. Ces blocs contiennent la pensée intérieure de Ryunosuke pendant la sélection de la pièce à conviction. Format identique au bloc DGS1 mais avec `<E027>` comme terminateur :
```json
{
  "en": "<E025 2><E007>(Did the two witnesses see two <E006>different<E007> moments of the\r\nsame crime?)<E027>",
  "fr": "<E025 2><E007>(Les deux témoins auraient-ils vu deux <E006>moments différents<E007> du même crime ?)<E027>"
}
```
Conserver les codes `<E007>` (couleur bleue) et `<E006>` (surligné orange) dans `"fr"` — sans codes, la stratégie 4 préserverait l'anglais (unsafe).

#### Format DGS1 — string GMD entière (`<RDFG>`) — fallback

Environ 372 entrées (EN/FR avec compte de blocs différent) restent en format full-GMD :

```json
{
  "_sce00_c000_0001_eng": [
    {
      "id": "001",
      "en": "<RDFG 1318><E800 93>...<E025 7>22nd November...<E023>...",
      "fr": "<RDFG 1318><E800 93>...<E025 7>22 novembre...<E023>..."
    }
  ]
}
```

- `wrap_dialogue_line()` et validations **ne sont PAS appliqués** (détection via `<RDFG `)

**Conventions communes :**
- **Sauts de ligne automatiques** (DGS2 seulement et blocs DGS2-style) — le traducteur n'a pas besoin de gérer les retours à la ligne
- **Maximum 2 lignes par boîte** — un `⚠ DÉPASSEMENT` est émis si c'est dépassé (DGS2 seulement)
- **Créer une 2ème boîte** : écrire `<PAGE>` dans `"fr"` (DGS2) — l'opener `<E025 N>` est injecté automatiquement
- Les entrées où EN visible == FR visible sont ignorées

**Pour obtenir le raw EN d'une entrée DGS2 :**
```bash
python3 tools/show_raw_blocks.py _sce00_c000_0010_eng "mot clé"
```

### 2. Détection et application des traductions

`tools/create_patch.py` :
1. Lit les JSON → construit `dict[en_brut → fr_text]` + `dict[en_visible → fr_text]` (double clé)
2. Pour chaque GMD dans l'ARC : appelle `translate_string(s, replacements)` sur chaque string
3. Génère un `.aapatch` couvrant DGS1 (GO/) et DGS2 (BB/) en un seul fichier

`translate_string()` dans `tools/gmd_utils.py` utilise 4 stratégies en cascade :

| Stratégie | Description | Cas d'usage |
|---|---|---|
| 1 | Correspondance exacte dans le texte brut | Prioritaire — matche via la clé brute `en_raw` |
| 2 | Normalisation CRLF→LF puis match | Différences `\r\n` vs `\n` |
| 3 | Regex flexible entre les mots (clés visibles seulement, **pas** `<E023>`/`<PAGE>`) | Fallback texte visible sans codes intercalés |
| 4 | Correspondance sur le texte visible du bloc `<E025>...<E023/PAGE/E027>` | Dernier recours — **ne devrait jamais arriver** si `en_raw` est correct |

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

### 1. Codes dans `"en"` absents de `"fr"` (DGS2)

Si un code présent dans `"en"` est absent de `"fr"` → `⚠ CODES MANQUANTS` à la génération. **Toujours corriger avant de finaliser.** Le traducteur doit placer TOUS les codes du bloc EN dans le FR aux positions sémantiquement équivalentes.

La stratégie 4 ne remplace pas si `"fr"` a des codes manquants ET le bloc original en a (préserve l'anglais). L'entrée reste en anglais jusqu'à correction.

### 2. Codes sémantiques — placement

Placer les codes à l'emplacement sémantiquement équivalent, **pas** par proportion mécanique. Exemple : `"Ah good,<E003 8> you're here"` → `"Ah,<E003 8> vous voilà"` (la pause est après "Ah," dans les deux cas, pas après le 2ème mot).

### 3. Stratégie 3 et les frontières de PAGE

La stratégie 3 (regex flexible) ne traverse pas `<E023>` ni `<PAGE>`. Si elle le faisait, elle fusionnerait plusieurs boîtes en une seule (3 lignes, débordement). Le SEP est `r'(?:(?:<(?!E023|/?PAGE)[^>]+>|\s)*)'`.

### 4. Backup obligatoire

Les backups sont créés automatiquement à côté des fichiers du jeu en `.arc.bak` lors du premier `rebuild_and_apply.py`. La restauration du backup avant application est obligatoire car `patch_all` vérifie le hash. `rebuild_and_apply.py` gère cela automatiquement.

---

## Mapping fichiers → JSON de traduction

### DGS1 (GO/) — un JSON monolithique par arc

Chaque arc est traduit via **un seul fichier JSON** (`sceXX.json`), contenant toutes les entrées de l'arc au format **full-GMD** (`<RDFG N>`).

> ⚠️ **Ne jamais découper en fichiers par chapitre (`sceXX_cYYY.json`).** Le format split perd les décalages `<E800>` intentionnels du patch original, ce qui corrompt les scènes 3D (écran beige). Voir branche `fix-3d-no-split`.

| ARC (`nativeDX11x64/archive/GO/`) | Fichier JSON | GMDs | État |
|---|---|---|---|
| `sce00_eng.arc` | `traductions/dgs1/sce00.json` | 60 | ✓ |
| `sce01_eng.arc` | `traductions/dgs1/sce01.json` | 58 | ✓ |
| `sce02_eng.arc` | `traductions/dgs1/sce02.json` | 47 | ✓ |
| `sce03_eng.arc` | `traductions/dgs1/sce03.json` | 85 | ✓ |
| `sce04_eng.arc` | `traductions/dgs1/sce04.json` | 158 | ✓ |

**Format :** toutes les entrées au format full-GMD `<RDFG N>` — chaque entrée remplace une string GMD entière.
**Les codes `<E800>` dans le FR peuvent différer du EN : c'est intentionnel, ne pas "corriger".**

### DGS2 (BB/) — un JSON par chapitre

| ARC (`nativeDX11x64/archive/BB/`) | Fichier JSON | État |
|---|---|---|
| `sce00_eng.arc` | `traductions/dgs2/sce00_c000.json` | ✓ Fait (148 entrées) |
| `sce00_eng.arc` | reste des GMD (c001–c009, evidence…) | à créer |
| `sce01_eng.arc` | — | à créer |
| `sce02_eng.arc` | — | à créer |
| `sce03_eng.arc` | — | à créer |
| `sce04_eng.arc` | — | à créer |

Pour ajouter une scène DGS2, ajouter une entrée dans `ARC_TRANSLATIONS` dans `tools/create_patch.py` :
```python
'nativeDX11x64/archive/BB/sce01_eng.arc': ['traductions/dgs2/sce01_c000.json'],
```

### Noms de personnages / UI (GO/)

Ces ARCs sont gérés via JSON (pas bsdiff) :

| ARC | Fichier JSON | Contenu |
|---|---|---|
| `nativeDX11x64/archive/GO/msg_title_eng.arc` | `traductions/legacy/archive/GO/msg_title_eng.json` | Noms courts (bulles), profils dossier, lieux, topics, cinématiques |
| `nativeDX11x64/archive/msg_cmn_eng.arc` | `traductions/legacy/archive/msg_cmn_eng.json` | Menus communs, titres chapitres, noms lieux |
| `nativeDX11x64/archive/msg_sys_eng.arc` | `traductions/legacy/archive/msg_sys_eng.json` | UI système, sauvegarde, options |
| `nativeDX11x64/archive/special_cmn_eng.arc` | `traductions/legacy/archive/special_cmn_eng.json` | Contenus spéciaux, galerie, musique, crédits |

Pour modifier du texte UI, éditer directement le JSON correspondant.

### Assets binaires et fichiers UI/legacy

Les fichiers de **texte UI** sont gérés via JSON (comme les scènes), dans `ARC_TRANSLATIONS` :

| ARC | Fichier JSON | Contenu |
|---|---|---|
| `nativeDX11x64/archive/msg_cmn_eng.arc` | `traductions/legacy/archive/msg_cmn_eng.json` | Menus communs, titres chapitres, noms lieux |
| `nativeDX11x64/archive/msg_sys_eng.arc` | `traductions/legacy/archive/msg_sys_eng.json` | UI système, sauvegarde, options |
| `nativeDX11x64/archive/special_cmn_eng.arc` | `traductions/legacy/archive/special_cmn_eng.json` | Contenus spéciaux, galerie, musique, crédits |

Ces ARCs sont **exclus du pipeline bsdiff** automatiquement (ils sont dans `OUR_SCENE_ARCS`).

Pour modifier du texte UI, éditer directement le JSON correspondant.

Les assets **binaires** (polices, textures, sons) restent dans `assets/patches/` comme bsdiffs.

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
├── gmd_utils.py                ← lecture/écriture GMD, wrap, translate_string (4 stratégies)
├── arc_utils.py                ← lecture/écriture ARC (zlib, index 144 bytes, data_start auto)
├── create_patch.py             ← pipeline complet DGS1+DGS2 : JSON → ARC patché → .aapatch
├── patch_legacy_text.py        ← applique des remplacements texte aux bsdiffs legacy + JSONs
├── extract_translations_dgs1.py ← extraction one-shot : patch_steam → traductions/dgs1/*.json
├── extract_legacy_patches.py   ← extraction one-shot : patch_steam → assets/patches/ (binaires)
├── convert_dgs1_format.py      ← convertit full-GMD → format bloc par bloc (one-shot, déjà fait)
├── split_dgs1_by_chapter.py    ← découpe sceXX.json en sceXX_cYYY.json (one-shot, déjà fait)
└── show_raw_blocks.py          ← affiche les blocs EN bruts d'un GMD (debug DGS2)

src/
└── aapatch.py                  ← format .aapatch, patch_all (hash + bsdiff4)

traductions/
├── dgs1/
│   ├── sceXX_cYYY.json         ← DGS1 traduit, découpé par chapitre (format bloc <E025>)
│   └── sceXX_misc.json         ← DGS1 : fichiers bg/chr/evidence/macro par arc
├── dgs2/
│   └── sce00_c000.json         ← DGS2 Épisode 1 intro (148 entrées, format bloc <E025>)
└── legacy/
    └── GO/msg/*.json           ← paires EN/FR extraites des fichiers UI/msg (documentation)

assets/
└── patches/
    ├── manifest.json           ← hash attendu + taille pour chaque fichier binaire
    └── nativeDX11x64/…/*.bsdiff ← bsdiffs pré-extraits (polices, UI, textures, sons)

rebuild_and_apply.py            ← script principal : génère + applique tout le patch

(dans le dossier jeu)
nativeDX11x64/archive/GO/sce*.arc.bak   ← backups originaux DGS1
nativeDX11x64/archive/BB/sce*.arc.bak   ← backups originaux DGS2
```

---

## Workflow pour traduire une nouvelle scène DGS2

1. **Extraire les GMD** d'un ARC et lister les dialogues :
```python
import sys, re
sys.path.insert(0, '/home/korphos/dev/DGS-FR')
from tools.arc_utils import read_arc
from tools.gmd_utils import read_gmd, get_strings, extract_dialogue_lines

# Utiliser le backup comme source
with open('/home/korphos/.steam/debian-installation/steamapps/common/TGAAC'
          '/nativeDX11x64/archive/BB/sce01_eng.arc.bak', 'rb') as f:
    arc_data = f.read()
entries = read_arc(arc_data)

for name, raw in entries:
    if '_sce01_c000_0000_eng' in name:
        gmd = read_gmd(raw)
        strings = get_strings(gmd)
        for si, li, text in extract_dialogue_lines(strings):
            print(f'[{si},{li}] {text}')
```

2. **Créer un fichier JSON** `traductions/dgs2/sce01_c000.json` au format `{ "_gmd_name": [ {id, en, fr}, ... ] }`.

3. **Ajouter l'entrée** dans `ARC_TRANSLATIONS` de `tools/create_patch.py` :
```python
'nativeDX11x64/archive/BB/sce01_eng.arc': ['traductions/dgs2/sce01_c000.json'],
```

4. **Régénérer et appliquer** :
```bash
python3 rebuild_and_apply.py
```
