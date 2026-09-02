# Authoritative data sources

`g2lex-data` owns the source inventory, pinned acquisition metadata, source-specific
transforms, deterministic G2Lex builds, manifests, releases, and catalog publication.
Runtime consumers use only published G2Lex assets. They do not download canonical source
files, run eSpeak, or import KokoroG2P.

## Production assets

| ID | Source and revision | Format | License | Transform |
| --- | --- | --- | --- | --- |
| `de-de:gold` | KokoroG2P German source, `kokorog2p-0.9.0` | Kokoro JSON | Apache-2.0 | none |
| `de-de:crane` | Crane Local AI German `de/de.tsv`, `bfd51698069b30e1b20bbf54479b55af50b4161d` | TSV | CC-BY-SA-4.0 | `de-crane-lowercase-lexhint-v1` |
| `de-de:espeak` | CSTR `espeak_de.tsv`, `eeac6ffc9271838fd63464a83d4b784ac75fc95b` | IPA TSV | CC-BY-SA-3.0 | `cstr-de-ipa-v1` |
| `de-de:olaph` | CSTR `olaph_de.txt`, `cedb4ada41a288549db36c53f9a1e6858a668624` | IPA TSV | MIT | `cstr-de-ipa-v1` |
| `en-us:cmudict` | CMUdict, `74790861f652b15e4ac49015a90074ad62a27690` | CMUdict | BSD-3-Clause | none |

The complete URLs, SHA-256 hashes, byte sizes, providers, attributions, and license
links are the source of truth in `datasets.toml` and each generated manifest. The
canonical German sources are redistributed here with their upstream notices. Source
acquisition is optional and always verifies the configured hash and size before replacing
a local file.

## Transform contracts

`de-crane-lowercase-lexhint-v1` applies NFC/lowercase key normalization, preserves source
pronunciation order, resolves POS selectors using the pinned LexHint artifact, and emits
a deterministic report. Its reviewed `die` collision policy is part of the published
transform contract.

`cstr-de-ipa-v1` skips only the documented first-row eSpeak header, removes one outer
IPA delimiter pair, preserves internal slashes and source pronunciation order, and
ignores only the optional OLaPh annotation field.

A semantic transform change requires a new transform ID and a new data release. The
English Kokoro `gold` and `silver` assets are not generic data and are intentionally not
migrated.
