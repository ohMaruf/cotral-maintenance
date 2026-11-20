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

## Selective tiling: the far band (`far_band.py`)

A sweep stays a Static API photo; only its far right-hand sidewalk (20-80 m away, 3-14 m right of the centre
line, 0-4 m above the ground) is re-rendered from tiles at 4x. Its box comes from the path geometry alone.
- Wide photos of found stops with the sign 20-70 m away (9 runs): the sign is inside the band in 36/39;
  6.7 tiles per photo (a full 640x640 tile render: 16). The 3 misses are f9388, where the path passes twice.
- f13310 opening photo 1: band 313x69 px -> 1250x276, 10 tiles; the Cotral panel and the benches are plain.

## Classic CV on the bands (`band_detect.py`)

Navy upright-rectangle detector on the clean bands: recall 14/36, 7.8 false alarms per band. Signs seen from
behind, backlit or shaded have no navy left; fences, cars and other blue signs do. Not usable as a gate.

## Tiles only where the sidewalk is (`sidewalk_tiles.py`)

The tiles a sign standing on each sidewalk spot (20-80 m, every 2 m, 3/8/14 m right) would fall in, against the
far band's rectangle, on the same 39 photos: band 6.4 tiles (zoom 4), sidewalk-only 5.9; same 36/39 coverage.
A zoom-4 tile is 22.5° x 22.5°, the far sidewalk ~8° tall: sky and asphalt mostly share the sidewalk's tiles,
so excluding them saves few tiles. They do cost image tokens, which cropping to the sidewalk saves.
