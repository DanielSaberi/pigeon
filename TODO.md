# TODO

- Explore blob-guided VLM cropping: when motion gating finds one or more connected change blobs, crop the VLM input around the relevant blob or merged blob region so lower VLM input resolutions may reduce inference cost without losing bird-detection accuracy.
- Implement fully robust audio/video capture with a single RTSP reader: replace the current OpenCV detection stream plus blocking ffmpeg follow-up recorder with one ffmpeg-based pipeline that opens the camera stream once, feeds decoded frames to motion/VLM detection, and can save post-detection clips with synchronized audio without pausing detection.
- Potential: add an Android alert heartbeat that plays a very short silent/near-silent sound every 295 seconds to keep the phone media route and Bluetooth speaker awake. Keep it opt-in via environment variables until we verify the CHARGE MINI actually sleeps or misses first playback.
