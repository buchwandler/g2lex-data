# Authoritative data sources

`g2lex-data` owns the source inventory, pinned acquisition metadata, source-specific
transforms, deterministic G2Lex builds, manifests, releases, and catalog publication.
Runtime consumers use only published G2Lex assets. They do not download canonical source
files, run eSpeak, or import KokoroG2P.

## Production assets

| ID              | Source and revision                                                                                  | Format         | License      | Transform                            |
| --------------- | ---------------------------------------------------------------------------------------------------- | -------------- | ------------ | ------------------------------------ |
| `de-de:gold`    | KokoroG2P German source, `kokorog2p-0.9.0`                                                           | Kokoro JSON    | Apache-2.0   | none                                 |
| `en-us:gold`    | KokoroG2P `lexicons/sources/en/us_gold.json` plus silver, `6ebdc3a89d608964e4b1b1b9958fb43b4574f04b` | Kokoro JSON    | Apache-2.0   | `kokoro-legacy-collapse-v1`          |
| `en-gb:gold`    | KokoroG2P `lexicons/sources/en/gb_gold.json` plus silver, `6ebdc3a89d608964e4b1b1b9958fb43b4574f04b` | Kokoro JSON    | Apache-2.0   | `kokoro-legacy-collapse-v1`          |
| `fr-fr:gold`    | KokoroG2P `lexicons/sources/fr/fr_gold.json`, `6ebdc3a89d608964e4b1b1b9958fb43b4574f04b`             | Kokoro JSON    | Apache-2.0   | `kokoro-legacy-collapse-v1`          |
| `de-de:crane`   | Crane Local AI German `de/de.tsv`, `bfd51698069b30e1b20bbf54479b55af50b4161d`                        | TSV            | CC-BY-SA-4.0 | `de-crane-lowercase-lexhint-v1`      |
| `de-de:espeak`  | CSTR `espeak_de.tsv`, `eeac6ffc9271838fd63464a83d4b784ac75fc95b`                                     | IPA TSV        | CC-BY-SA-3.0 | `cstr-de-ipa-v1`                     |
| `de-de:olaph`   | CSTR `olaph_de.txt`, `cedb4ada41a288549db36c53f9a1e6858a668624`                                      | IPA TSV        | MIT          | `cstr-de-ipa-v1`                     |
| `sv-se:nst`     | Joakim/kokoro-sv-g2p `g2p/lexicon.tsv`, `d19dd10`                                                    | TSV            | Apache-2.0   | none                                 |
| `en-us:cmudict` | CMUdict, `74790861f652b15e4ac49015a90074ad62a27690`                                                  | CMUdict        | BSD-3-Clause | none                                 |
| `en-us:lexhint` | LexHint datasets English dictionary, `data-en-2026.08.28`                                            | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `en-gb:lexhint` | Same pinned English artifact, locale-derived `en_GB`                                                 | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `de-de:lexhint` | LexHint datasets German dictionary, `data-de-2026.08.28`                                             | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `cs:lexhint`    | LexHint datasets Czech dictionary, `data-cs-2026.08.28`                                              | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `el:lexhint`    | LexHint datasets Greek dictionary, `data-el-2026.09.08`                                              | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `es:lexhint`    | LexHint datasets Spanish dictionary, `data-es-2026.08.28`                                            | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `fr:lexhint`    | LexHint datasets French dictionary, `data-fr-2026.08.28`                                             | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `id:lexhint`    | LexHint datasets Indonesian dictionary, `data-id-2026.09.08`                                         | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `it:lexhint`    | LexHint datasets Italian dictionary, `data-it-2026.08.28`                                            | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `ku:lexhint`    | LexHint datasets Kurdish dictionary, `data-ku-2026.09.08`                                            | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `ms:lexhint`    | LexHint datasets Malay dictionary, `data-ms-2026.09.08`                                              | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `pl:lexhint`    | LexHint datasets Polish dictionary, `data-pl-2026.09.08`                                             | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `tr:lexhint`    | LexHint datasets Turkish dictionary, `data-tr-2026.09.08`                                            | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |

| `ja:lexhint` | LexHint datasets Japanese dictionary, `data-ja-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `ko:lexhint` | LexHint datasets Korean dictionary, `data-ko-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `pt:lexhint` | LexHint datasets Portuguese dictionary, `data-pt-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `ru:lexhint` | LexHint datasets Russian dictionary, `data-ru-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `th:lexhint` | LexHint datasets Thai dictionary, `data-th-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `vi:lexhint` | LexHint datasets Vietnamese dictionary, `data-vi-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |
| `zh:lexhint` | LexHint datasets Chinese dictionary, `data-zh-2026.09.03` | LexHint SQLite | CC-BY-SA-4.0 | `lexhint-pronunciation-lowercase-v1` |

## Swedish NST ownership migration

The stable ID `sv-se:nst` contains 812,343 parsed IPA entries from the immutable `d19dd10` revision of `Joakim/kokoro-sv-g2p`. The source is exactly 38,008,908 bytes with SHA-256 `65eb3aae9c737f6d04c22a44b2ab836d1ec01f682b1cdee07bb2209852355296`. It uses the generic TSV parser and no semantic transform.

Canonical source and generated G2Lex ownership moved from KokoroG2P to `g2lex-data`. The migration is gated by logical parity with the former `sv_nst.g2lex` asset. Existing Apache-2.0 provider, revision, URL, and attribution metadata are preserved pending any separately required NST provenance notice.

## Kokoro English and French migration

The five source files under `sources/kokorog2p` were copied from KokoroG2P revision `6ebdc3a89d608964e4b1b1b9958fb43b4574f04b`. Their exact SHA-256 hashes and byte sizes are pinned in `datasets.toml`; the source URL, Apache-2.0 license, and KokoroG2P contributor attribution are retained there and in generated manifests.

| Source                                |     Bytes | SHA-256                                                            |
| ------------------------------------- | --------: | ------------------------------------------------------------------ |
| `sources/kokorog2p/en/us_gold.json`   | 3,000,991 | `50a8a07a5d5054c25cac1f4e2f0efc31a0a104e0d92c6ddc599772c183e1a86d` |
| `sources/kokorog2p/en/us_silver.json` | 3,099,518 | `067c30f29524585b479affdef2823d6c1e27c59d6d6dfb1694be676bba1185f1` |
| `sources/kokorog2p/en/gb_gold.json`   | 2,839,077 | `bcbc593a5fe247d92ee584ffb6302d326b4f99f652c634991206e3f848d36cac` |
| `sources/kokorog2p/en/gb_silver.json` | 3,663,899 | `6c062fa3dcab1a949855ff9350bd327335cb3c501218180e052d0e3e4faf5883` |
| `sources/kokorog2p/fr/fr_gold.json`   |   376,263 | `0d5dcd4a6fec8c8decde6403880e41c7b8d6f6c300928eb81f2edc42f811e081` |

The published IDs intentionally collapse the old tiers: `en-us:gold` is gold first then silver, `en-gb:gold` is gold first then silver, and `fr-fr:gold` is the case-alias-expanded French source. `gold` now names the consolidated reviewed lexicon and is not the old tier boundary. The transform materializes case aliases and preserves Kokoro strings, tagged values, and variants as `kokoro-v1`; it does not convert them to IPA.

## Frozen German migration release

The four German migration assets are available in the immutable `data-2026.09.02` release. The published catalog and manifests were verified against the KokoroG2P baseline on 2026-09-03. All four records use locale `de-DE`, kind `pronunciation`, and IPA encoding.

| ID             | Entries | Asset SHA-256                                                      | Manifest SHA-256                                                   | Logical SHA-256                                                    |
| -------------- | ------: | ------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `de-de:gold`   |  738427 | `558c17c5bfe12e4e405126997730c5303a736d343e4ced587ed8adf53023c392` | `a725652ed89f57770078ed5392768cb97267fa64bed164e2f0c612209fc44c59` | `530f4787a2accd9824526749b90f43d4edaf2506f0aa385056a83913cb6ee48a` |
| `de-de:crane`  |  826871 | `dc94cf99aa309dbb3eaf4f15f974c5aa27a9b43e057511f46140826a5c8fc593` | `694a31a16376f742eacfb2680aefd9ab062f891434beabf3e50e8baee806b1b3` | `2381391dc5c0ea083816c1d3cac9002d16750e05038dc3ac97690115b9007efa` |
| `de-de:espeak` |  667295 | `5445e63e9cfafa0ffbd517144c38d8b63cb6a37bf68a9399c4a83efea9abf167` | `3a6176fdc714088b468e9dadd4e015547b0168708b3bdd50e60083aeaeb24639` | `4c975e8348d2e8cb288f9b9530dcf26d7ac1527fec2d43457fa77481d562279d` |
| `de-de:olaph`  |  965839 | `90cb44a82b6330f48627805ee25f75568e047d72e1bd610384fdca7a68cc9743` | `c50436f5b8274bc1983638cd0cfe67ca7145a9056933749c6ac4f5954a9ec847` | `c0dc2c87cf6f229ae88e66c2f4b3c03876f9f95df615e82c0133f0e3778c296d` |

The release metadata records the source revisions and licenses in the production-assets table above. The Crane release manifest was generated with LexHint `0.4.2`; the current producer configuration may use a newer LexHint version for a future release, but `data-2026.09.02` must never be rewritten.

Verification covered remote asset and manifest hashes and sizes, immutable `release.json`, G2Lex entry counts and logical hashes, source pins, transforms, catalog IDs, and exact logical parity with the KokoroG2P baseline.
The complete URLs, SHA-256 hashes, byte sizes, providers, attributions, and license
links are the source of truth in `datasets.toml` and each generated manifest. The
canonical German sources are redistributed here with their upstream notices. Source
acquisition is optional and always verifies the configured hash and size before replacing
a local file.

LexHint records resolve managed local SQLite artifacts from published `buchwandler/lexhint-datasets` dictionary releases. The underlying dictionary text is derived from Wiktionary through Wiktextract and Kaikki. The 19 configured physical base-language sources are `cs`, `de`, `el`, `en`, `es`, `fr`, `id`, `it`, `ja`, `ko`, `ku`, `ms`, `pl`, `pt`, `ru`, `th`, `tr`, `vi`, and `zh`. The `g2lex-data` records pin the installed uncompressed SQLite hash and size, while the source artifact and LexHint 0.4.4 package versions are immutable build inputs. The resulting G2Lex assets are generic IPA outputs. One English artifact produces the `en-US` and `en-GB` locale-derived assets; every other represented language is a base-language record without regional pronunciation claims.

## Transform contracts

`de-crane-lowercase-lexhint-v1` applies NFC/lowercase key normalization, preserves source
pronunciation order, resolves POS selectors using the pinned LexHint artifact, and emits
a deterministic report. Its reviewed `die` collision policy is part of the published
transform contract.

`cstr-de-ipa-v1` skips only the documented first-row eSpeak header, removes one outer
IPA delimiter pair, preserves internal slashes and source pronunciation order, and
ignores only the optional OLaPh annotation field.

A semantic transform change requires a new transform ID and a new data release. The Kokoro English and French sources are now authoritative migration inputs in `g2lex-data`, while consumers use only the published consolidated IDs.
