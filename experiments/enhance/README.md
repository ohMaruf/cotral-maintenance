# Making Cotral blue visible in wide photos (2026-11-20)

Question: can preprocessing (boosting Cotral navy) make far signs stand out in sweeps?
Cases: f13310 (sign in opening photo 1 at (245, 488) on the 0-1000 grid, never zoomed),
f306 (sign at -44 m, missed in run 11 sweep photo 6).

- `cotral_blue.py`: navy on the reference sign is H 219, S 0.42, V 0.33. Recolouring navy pixels does not work
  on Static API photos: shaded asphalt (H 224, S 0.32) matches better than a far sign (f306: S 0.10, V 0.60).
- `blobs.py`: navy blobs as a sign detector, on the wide photos of every found stop in 9 runs: 124 other
  blobs per photo, so its 45/68 hits are mostly chance.
- Cause: the Static API's 640 px JPEG. The same 640x640 / 110° view rendered from Map Tiles at zoom 3
  (`render.render_view`, 16 tiles) shows the f13310 sign as a clean saturated blue panel; in the Static API
  photo it is a grey-blue smudge in block artefacts. f306 gains little (back of the sign / backlit).
  At 3x (1920 px, 36 tiles) the f13310 sign shows its "cotral" logo and the benches.
