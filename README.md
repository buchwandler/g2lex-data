# g2lex-data

`g2lex-data` is the reproducible producer and publisher for generic [G2Lex](https://github.com/buchwandler/g2lex) pronunciation and membership assets. The runtime consumer is [Lexphon](https://github.com/buchwandler/lexphon).

## Ownership boundary

This repository is the authoritative source, build, and release repository for externally distributed G2Lex datasets, including reviewed application-specific encodings such as the legacy Kokoro `kokoro-v1` English and French pronunciation assets. It owns source inventories, immutable source pins, acquisition checks, source-specific transforms, deterministic compilation, lossless verification, manifests, licenses, immutable data releases, and catalog publication. It does not own tokenization, sentence phonemization, or runtime fallback behavior.

## Configured production assets

The production tranche contains `de-de:gold`, `de-de:crane`, `de-de:espeak`, `de-de:olaph`, `en-us:cmudict`, `en-us:gold`, `en-gb:gold`, `fr-fr:gold`, `en-us:lexhint`, `en-gb:lexhint`, `de-de:lexhint`, `cs:lexhint`, `el:lexhint`, `es:lexhint`, `fr:lexhint`, `id:lexhint`, `it:lexhint`, `ja:lexhint`, `ko:lexhint`, `ku:lexhint`, `ms:lexhint`, `pl:lexhint`, `pt:lexhint`, `pt-br:lexhint`, `pt-pt:lexhint`, `ru:lexhint`, `th:lexhint`, `tr:lexhint`, `vi:lexhint`, `zh:lexhint`, and `sv-se:nst`. The demo fixtures remain for fast contract tests.
Pronunciation encodings are `ipa`, `arpabet`, and the reviewed legacy `kokoro-v1`; membership assets use `none`. The old Kokoro tiers are consolidated as `en-us:gold` from `en-us:gold` plus `en-us:silver`, `en-gb:gold` from `en-gb:gold` plus `en-gb:silver`, and `fr-fr:gold` from `fr-fr:gold`. No English silver ID is published.

LexHint currently exposes 55 physical language/source pairs from the source-qualified v2 catalog: 36 English-Wiktionary-derived pairs and 19 native-Wiktionary-derived pairs. g2lex-data publishes 58 direct LexHint assets: `pt:lexhint` is the locale-neutral/all-retained-evidence Portuguese asset, while `pt-br:lexhint` and `pt-pt:lexhint` are Brazilian and European Portuguese projections. All three preferred Portuguese assets use the same English-Wiktionary-derived physical `pt` dictionary; `lexhint-native` remains a separate source-variant choice. English likewise derives the locale-filtered `en-US` and `en-GB` outputs from one physical source. The producer resolves the newest compatible installed dictionary without a dated selector and records exact release and SQLite provenance in each manifest. These remain generic IPA pronunciation lexicons, not Kokoro lexicons.
Source provenance and redistribution status are documented in [DATA_SOURCES.md](DATA_SOURCES.md).

## Build and validate

```bash
python -m pip install -e ".[dev]"
# Preferred English-Wiktionary sources
for lang in ar az bg ca ceb cs de el en es fr ga he hi hu hy it ja ko la lt lv mr nl pl pt ro ru sv ta te tl tr uk ur vi zh; do
  lexhint dataset download "$lang" --variant dictionary --source-variant english
done

# Native-Wiktionary alternatives
for lang in cs de es fr id it ja ko ku ms pl pt ru th tr vi zh; do
  lexhint dataset download "$lang" --variant dictionary --source-variant native
done
python -m g2lex_data sources
python -m g2lex_data build
python -m g2lex_data validate --catalog
python -m g2lex_data parity --baseline-dir /path/to/kokorog2p
pytest
ruff check .
```

The parity command accepts either a KokoroG2P checkout root or its
`kokorog2p/lexicons/data` directory. Normal builds never import KokoroG2P.

## Immutable releases

Data versions are independent from the Python package version. A release such as
`data-2026.09.0` stages all configured assets, manifests, `catalog.json`, and
`release.json` under `dist/data-2026.09.0/`. Existing release directories are never
replaced. Catalog entries contain the stable ID, language, encoding, release tag, asset
and manifest URLs, hashes, sizes, logical hash, and license summary needed by Lexphon.

```bash
python -m g2lex_data release --data-version data-2026.09.0
```
