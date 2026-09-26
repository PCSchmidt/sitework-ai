# Dataset manifests

One manifest per dataset, clip set, or model weight file the demo or evaluation harnesses use.
Nothing large is committed to git: the manifests record where each thing came from, its
license, and (where it matters for reproducing a published number) a SHA-256 hash to check a
download against.

| Manifest | What it pins | Hashes |
| --- | --- | --- |
| `pexels-demo-clips.yaml` | The stock clips the simulated cameras loop, plus their 1080p transcodes | every used clip and transcode |
| `yolo11-weights.yaml` | Ultralytics YOLO11s (default) and YOLO11n detector weights; AGPL-3.0 note | both `.pt` files, checked against the release URLs |
| `mot17.yaml` | MOT17 pedestrian-tracking benchmark (HF mirror), used for MOTA/IDF1 | mirror commit pinned instead; research-only, never committed |
| `mendeley-construction.yaml` | Construction-machinery detection frames (CC BY 4.0) | archive hash |
| `hf-physicalai-warehouse.yaml` | NVIDIA synthetic warehouse stills used by spike-02 | index files |
| `dev-own-footage.yaml` | The author's own phone clip used to validate calibration on real footage | clip hash |

Template for a new manifest:

```yaml
name: <dataset or clip id>
version: <upstream version or date>
url: <source>
license: <SPDX or research terms summary>
redistribution: allowed | research-only | prohibited
files:
  - path: <local path>
    sha256: <file hash>
```

Every number in `docs/benchmarks.md` should be regenerable from these pinned inputs
(docs/09 §5). TensorRT `.engine` files are deliberately not hashed: they are compiled for one
GPU and TensorRT version and aren't portable.
