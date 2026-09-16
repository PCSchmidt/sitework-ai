# Dataset manifests

One manifest per dataset/clip used by the demo or eval harness:

```yaml
name: <dataset or clip id>
version: <upstream version or date>
url: <source>
license: <SPDX or research terms summary>
redistribution: allowed | research-only | prohibited
sha256: <archive hash>
files:
  - path: assets/clips/<file>.mp4
    sha256: <file hash>
```

Manifests are created in M1 when the actual demo clips are selected (roadmap M1 task).
Every number in docs/benchmarks.md must be regenerable from pinned manifests (docs/09 §5).
