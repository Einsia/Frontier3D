# Frozen L3 external asset metadata

These are the original organizer manifests and Poly Haven download plan. Their
bytes and hashes are preserved so task `catalog_sha256` and `libraries` bindings
stay valid. The metadata contains source URLs, authors, licenses, paths and
file hashes. The original Kenney source ZIPs (about 35 MiB) are bundled under `archives/`.
Their archive hashes match the original lock. The upstream URLs returned HTML
during release validation, so local copies remove that installation dependency.
Poly Haven textures (about 35.1 GiB) remain external downloads.
The three libraries contain 13,351 files, about 35.2 GiB in total.

Run `python harness/L3/release/prepare_assets.py fetch --root /path/to/assets`
from the repository root, then use `verify` to check all downloaded bytes.
The fetcher selects only manifest-listed members from the bundled ZIPs and
streams Poly Haven texture files.
It checks every file against the frozen SHA-256, without calling model services.
A missing upstream URL or changed archive is a preparation error, not permission
to substitute a new library version. Preserve the shipped manifest bytes.

Poly Haven and Kenney asset licenses and attribution remain those recorded in
these manifests and source packs. Provider metadata is not blanket relicensed
as CC0 by the repository's software license. See the root THIRD_PARTY_NOTICES.md.
