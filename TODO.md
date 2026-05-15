# TODO

- Explore blob-guided VLM cropping: when motion gating finds one or more connected change blobs, crop the VLM input around the relevant blob or merged blob region so lower VLM input resolutions may reduce inference cost without losing bird-detection accuracy.
- Potential: add pre-roll to deterrence AV clips by keeping a short rolling buffer before the first positive bird result, so review videos include the few seconds before detection.
- Potential: add an Android alert heartbeat that plays a very short silent/near-silent sound every 295 seconds to keep the phone media route and Bluetooth speaker awake. Keep it opt-in via environment variables until we verify the CHARGE MINI actually sleeps or misses first playback.
