# Demo clips

The "cameras" in this project are short stock video clips from [Pexels](https://www.pexels.com/),
looped by MediaMTX so the vision pipeline sees them as live RTSP camera feeds. No real site is
monitored.

The clips are **git-ignored** (`*.mp4`), so a fresh clone has none. The full stack (`make up`)
needs the three camera clips before it will work; the replay demo (`make replay-up`) needs none.

**Selected set, source links, and SHA-256 hashes:** `data/manifests/pexels-demo-clips.yaml`. Three
clips map 1:1 to the cameras in `config/cameras.yaml` (dock / warehouse aisle / excavator yard),
plus one spare.

To set them up:

1. Download each clip from its `source` URL in the manifest into this folder, under the `file`
   name it lists.
2. Make the 1080p versions the stack actually streams (`docker/mediamtx.yml` plays the
   `*_1080p.mp4` files; spike-00 found native-4K decoding was the throughput bottleneck):

   ```bash
   ffmpeg -i forklift_workers_interaction.mp4 -vf scale=1920:1080 -r 25 -c:v libx264 -an forklift_workers_interaction_1080p.mp4
   ```

   Repeat for `worker_walking_aisle` and `excavator_site_01`. The hashes won't match the
   manifest's `transcode` entries (those record the exact files the published benchmarks used),
   but the result is equivalent for running the stack.

Preview frames live in `_preview/` (also git-ignored).
