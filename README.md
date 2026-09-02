# g2lex-data

Reproducible source acquisition, provenance, validation, release packaging, and catalog publication for lexicons compiled with [G2Lex](https://github.com/buchwandler/g2lex).

`g2lex-data` is a **producer repository**. It does not phonemize text and it does not contain Kokoro-specific policy. The intended runtime consumer is [Lexphon](https://github.com/buchwandler/lexphon).

## Architecture

```text
upstream dictionaries / LexHint / project-owned data
                     |
                     v
                 g2lex-data
       source pinning + transformation
       deterministic G2Lex compilation
       exact lossless verification
       manifests + licenses + attribution
       immutable data releases + catalog
                     |
                     v
                   lexphon
       install/cache + lookup + phonemization
                     |
                     v
                 applications
```

## Dynamic versioning

The Python tooling uses a small dependency-free Git-derived version helper, exposed through `project.dynamic = ["version"]`. A repository tag such as `v0.2.0` produces version `0.2.0`; commits after a tag receive a derived development/post version. Source snapshots without Git metadata use the fallback `0.1.0`, and an environment variable can override the build version.

Data artifacts are independently versioned by `--data-version` and released under tags such as `data-0.1.0`.

## MVP

The fixtures cover three different data contracts:

- `de-de:demo`: typed/tagged IPA values and ordered pronunciation variants;
- `en-us:demo-cmu`: CMU-style ARPABET with multiple pronunciations for `read`;
- `ja-jp:demo-words`: membership-only lexicon.

```bash
python -m pip install -e ".[dev]"
g2lex-data build
g2lex-data validate
g2lex-data catalog --data-version 0.1.0
g2lex-data release --data-version 0.1.0
pytest
```

Release staging is written to `dist/data-<version>/`.

## Catalog contract

`catalog/catalog.json` is a discovery index, not the detailed provenance record. Each entry carries:

- stable dataset id and BCP-47 language;
- pronunciation encoding (`ipa`, `arpabet`, or `none`);
- immutable asset and manifest URLs;
- SHA-256 and byte size;
- G2Lex format/schema, logical hash and entry count;
- data version, release tag, provider, revision, and license summary.

Lexphon verifies the downloaded bytes against this catalog before making an asset visible in its local store.
