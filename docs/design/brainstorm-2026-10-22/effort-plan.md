# Effort probe on the OZ/1g wire (frozen before the first counted call, 2026-10-23)

Question: does `--effort medium` cut Haiku 5.5's thinking on OZ/1g without losing correct work?
Evidence so far: on an earlier native-JSON wire (live12), Haiku medium kept 320/320 with output 3230 vs 4469 at
high; low lost replies (3/5 valid). OZ/1g at default effort: output about 6,100 tokens per 64-job call, thinking 4,753.

Design: `bench/live/run1g.py`, ARM=H, MODEL=haiku, N=64, seeds 3205 to 3209, no 0.8 baseline (BASE empty).
Two runs on the same seeds, one after the other: default effort (no flag), then EFFORT=medium.
Concurrency 1, no reply retry, strict acceptance, deterministic oracles; the harness stops an arm at its second
failed packet.

Gate: medium is promoted for Haiku only if it has 5/5 replies accepted, 320/320 correct, and lower total tokens
per verified job than default on the same seeds. Otherwise default stays, and the result is published as measured.
Medium is not qualified by this probe for any other model.
