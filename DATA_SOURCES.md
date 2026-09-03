# Authoritative data sources

`g2lex-data` owns the source inventory, pinned acquisition metadata, source-specific
transforms, deterministic G2Lex builds, manifests, releases, and catalog publication.
Runtime consumers use only published G2Lex assets. They do not download canonical source
files, run eSpeak, or import KokoroG2P.

## Production assets

| ID              | Source and revision                                                           | Format         | License      | Transform                            |
| --------------- | ----------------------------------------------------------------------------- | -------------- | ------------ | ------------------------------------ |
| `de-de:gold`    | KokoroG2P German source, `kokorog2p-0.9.0`                                    | Kokoro JSON    | Apache-2.0   | none                                 |
| `de-de:crane`   | Crane Local AI German `de/de.tsv`, `bfd51698069b30e1b20bbf54479b55af50b4161d` | TSV            | CC-BY-SA-4.0 | `de-crane-lowercase-lexhint-v1`      |
| `de-de:espeak`  | CSTR `espeak_de.tsv`, `eeac6ffc9271838fd63464a83d4b784ac75fc95b`              | IPA TSV        | CC-BY-SA-3.0 | `cstr-de-ipa-v1`                     |
| `de-de:olaph`   | CSTR `olaph_de.txt`, `cedb4ada41a288549db36c53f9a1e6858a668624`               | IPA TSV        | MIT          | `cstr-de-ipa-v1`                     |
| `en-us:cmudict` | CMUdict, `74790861f652b15e4ac49015a90074ad62a27690`                           | CMUdict        | BSD-3-Clause | none                                 |
| `en-us:lexhint` | LexHint datasets English dictionary, `data-en-2026.08.28`                     | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `en-gb:lexhint` | Same pinned English artifact, locale-derived `en_GB`                          | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `de-de:lexhint` | LexHint datasets German dictionary, `data-de-2026.08.28`                      | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |


## Frozen German migration release

The four German migration assets are available in the immutable `data-2026.09.02` release. The published catalog and manifests were verified against the KokoroG2P baseline on 2026-09-03. All four records use locale `de-DE`, kind `pronunciation`, and IPA encoding.

| ID | Entries | Asset SHA-256 | Manifest SHA-256 | Logical SHA-256 |
| --- | ---: | --- | --- | --- |
| `de-de:gold` | 738427 | `558c17c5bfe12e4e405126997730c5303a736d343e4ced587ed8adf53023c392` | `a725652ed89f57770078ed5392768cb97267fa64bed164e2f0c612209fc44c59` | `530f4787a2accd9824526749b90f43d4edaf2506f0aa385056a83913cb6ee48a` |
| `de-de:crane` | 826871 | `dc94cf99aa309dbb3eaf4f15f974c5aa27a9b43e057511f46140826a5c8fc593` | `694a31a16376f742eacfb2680aefd9ab062f891434beabf3e50e8baee806b1b3` | `2381391dc5c0ea083816c1d3cac9002d16750e05038dc3ac97690115b9007efa` |
| `de-de:espeak` | 667295 | `5445e63e9cfafa0ffbd517144c38d8b63cb6a37bf68a9399c4a83efea9abf167` | `3a6176fdc714088b468e9dadd4e015547b0168708b3bdd50e60083aeaeb24639` | `4c975e8348d2e8cb288f9b9530dcf26d7ac1527fec2d43457fa77481d562279d` |
| `de-de:olaph` | 965839 | `90cb44a82b6330f48627805ee25f75568e047d72e1bd610384fdca7a68cc9743` | `c50436f5b8274bc1983638cd0cfe67ca7145a9056933749c6ac4f5954a9ec847` | `c0dc2c87cf6f229ae88e66c2f4b3c03876f9f95df615e82c0133f0e3778c296d` |

The release metadata records the source revisions and licenses in the production-assets table above. The Crane release manifest was generated with LexHint `0.4.2`; the current producer configuration may use a newer LexHint version for a future release, but `data-2026.09.02` must never be rewritten.

Verification covered remote asset and manifest hashes and sizes, immutable `release.json`, G2Lex entry counts and logical hashes, source pins, transforms, catalog IDs, and exact logical parity with the KokoroG2P baseline.
The complete URLs, SHA-256 hashes, byte sizes, providers, attributions, and license
links are the source of truth in `datasets.toml` and each generated manifest. The
canonical German sources are redistributed here with their upstream notices. Source
acquisition is optional and always verifies the configured hash and size before replacing
a local file.

LexHint records resolve managed local SQLite artifacts. The English US and GB assets use one physical English artifact and differ only by the LexHint locale derivation. Generated pronunciation assets are generic IPA and retain Wiktionary, Wiktextract, Kaikki, and LexHint dataset attribution; they are not covered only by this repository's Apache license.

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
