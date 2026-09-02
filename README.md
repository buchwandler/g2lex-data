# g2lex-data

`g2lex-data` is the reproducible producer and publisher for generic [G2Lex](https://github.com/buchwandler/g2lex) pronunciation and membership assets. The runtime consumer is [Lexphon](https://github.com/buchwandler/lexphon).

## Ownership boundary

This repository owns source inventories, immutable source pins, acquisition checks,
source-specific transforms, deterministic compilation, lossless verification, manifests,
licenses, immutable data releases, and catalog publication. It does not own tokenization,
lexicon precedence, Kokoro conversion or ratings, sentence phonemization, or runtime
fallback behavior.

## Configured production assets

The first production tranche contains `de-de:gold`, `de-de:crane`, `de-de:espeak`,
`de-de:olaph`, and `en-us:cmudict`. The demo fixtures remain for fast contract tests.
Generic pronunciation encodings are `ipa` and `arpabet`; membership assets use `none`.
Kokoro-specific `kokoro-v1` assets are deliberately excluded.

Source provenance and redistribution status are documented in [DATA_SOURCES.md](DATA_SOURCES.md).

## Build and validate

```bash
python -m pip install -e ".[dev]"
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
