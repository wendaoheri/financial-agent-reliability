# PER-28 public benchmark seed bundle v2

Version 2 supersedes the revoked v1 bundle without changing any v1 file or
hash. The v1 bundle hash
`7a05f78739f6751778cac31cde031bf56721fa7429a68ce8aa6b1ff576de87a7`
is retained only as audit evidence; it is not a Stage 3 input because it used a
future-dated retrieval constant and overstated the FinQA dataset license.

The v2 collector samples the live UTC clock immediately before each WDI request
and after reading each response body. `collection_session.v2.json` binds the 15
request/retrieval intervals to raw-response hashes. Offline rebuilds consume
those frozen timestamps and never synthesize a new collection time.

FinQA is now recorded conservatively: the official repository root `LICENSE`
is MIT, but no separate dataset license was evidenced. The catalog therefore
makes no CC-BY claim, does not assert a FinQA content-redistribution right, and
continues to use FinQA only as non-copying structural inspiration. All factual
inputs remain newly frozen WDI observations under the World Bank's published
CC-BY-4.0 data license.

The allocation remains exactly 15 public families and 45 cases: 22 Gold and 23
Silver, with three variants per family. Combined with the separately frozen
workflow bundle, the benchmark remains 46 Gold / 44 Silver and 50/50 by track.
No candidate model was queried and the release gate remains closed pending
independent review.

Rebuild from frozen raw responses:

```text
uv run python cases/public/v2/build_public_cases_v2.py build
```

The v2 fetch command is deliberately single-use and refuses to overwrite any
raw capture. A new collection must be published as a new version:

```text
uv run python cases/public/v2/build_public_cases_v2.py fetch-and-build
```
