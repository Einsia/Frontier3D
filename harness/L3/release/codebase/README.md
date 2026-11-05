# L3 implementation

Use the shared public CLI from the repository root:

```sh
python -m benchmark run --help
python -m benchmark doctor --level 3 --resources-only
```

Installation, `.env` configuration, generation, independent UE collection,
v5 scoring and export are in the [root README](../../../../README.md#configure-l3-ue).
This directory retains the native task schema, UE plugin, geometry libraries and
shared modules. The public CLI isolates its imports in subprocesses and combines
its normalized scores with L1/L2 results. Historical experiment state and private
provider files are excluded from the source release.
