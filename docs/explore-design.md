# Design: an LLM explorer that finds a bus stop in Street View

Status: draft for discussion, version 3 (2026-11-07). Nothing of the explorer is
implemented yet; the data it needs is (§4).
Branch: `experiment/streetview-agent-explore`.

**Principles.**
- **Good first, fast later.** We build the best explorer we can; speed and cost
  come after it works.
- **The tooling makes the difference, not the model.** Capable models are roughly
  alike. What they need is a harness that gives them the right facts and the right
  actions: the bus's real path, every hint we have, honest bookkeeping of what has
  been seen, and tools that speak in metres along that path.
- **The harness does geometry and bookkeeping; the LLM decides where to look.**
  Programmatic jumps failed (the Clef runs). Clef can't call tools, so it is
  dropped; the explorer is an LLM.
- **Context is not the constraint.** Plan for 100K tokens: every photo stays in the
  conversation. A local model now (Qwen3.8-27B, 2-bit), bigger ones later.

## 1. Contract

**Input**, per stop:
- the stop id and name
- the GTFS trips serving it: their shapes, previous and next stops
- **starting positions:** OSM when an object can be tied to the stop (§4.4), else Places, else GTFS
- **hints:** every stop-like OSM object near the bus's path, of any kind (§4.4)

**Output**
- `status`: `found` (a stop seen and **confirmed**, §3), `not_found` (all 14 photos
  used, nothing confirmed), or `no_imagery` (no panorama from 2024 onwards on the
  path)
- `lat`, `lon` (only when found) and `position_basis`: `triangulated`,
  `single_ray_sidewalk` or `panorama` (§5)
- `evidence`: `cotral_sign`, `other_stop_sign`, `shelter_only` or `road_marking`
- `scan_date`, `confidence`, `stop_id_read` (plate text, when a zoom reads it)
- `nearest_source`: which input (Places, GTFS, an OSM hint) was closest to the
  answer, and how far
- `unscanned`: the stretches of the path with no Street View, and how likely the
  stop is to be there. A `not_found` with a large unscanned share means "check by
  hand", not "missing".
- the transcript, photos and debug maps

The LLM never writes coordinates: it points at things in photos; code computes
positions (§5).

**Stopping rule.** Stop only when a stop is confirmed; otherwise use all 14 photos,
then `not_found`. No "give up".

## 2. What we learned from the Clef run (6 stops)

- **Navigation failed.** The stop was behind the start in 2 of 3 findable stops and
  it walked ahead; in the third it photographed the wrong sidewalk. Its confidence in
  each move stayed near 0.2: guessing. Text history didn't make it plan.
- **A false positive:** a blue pedestrian-crossing sign at p = 0.86 (f10923).
- **A thin harness:** fixed 8 or 16 m moves, the road as one straight line, no map
  of panoramas, no confirmation step, no hints, sign position in 5 bins.

## 3. Recognising the stop, and not being fooled

**Existence over branding.** Another operator's sign, a generic stop sign, a
shelter, or stop markings on the road all count as found. A missing Cotral sign is a
maintenance finding, later.

| `evidence` | Meaning |
|---|---|
| `cotral_sign` | Navy panel, "FERMATA", white Cotral logo, plate with the stop id (`GROUND_TRUTH/stop_sign_reference.png`). |
| `other_stop_sign` | A bus stop sign that isn't Cotral's. |
| `shelter_only` | A bus shelter, no sign seen. |
| `road_marking` | Only stop markings ("BUS", yellow zig-zag) or a bus lay-by. |

**Two steps: spot, then confirm.**
1. **Spot.** The explorer marks *candidates* in wide photos: a panel on a pole, a
   shelter, a bench at the kerb, people waiting, markings. A candidate is never a
   result.
2. **Confirm.** A narrow photo (fov about 20°) of the candidate goes to a **separate,
   fresh LLM call** that has seen nothing of the search, so it can't be talked into
   "this must be it". It answers a checklist, each item yes / no / can't tell:
   - **stop features:** "FERMATA" or "BUS" text; the Cotral logo; a timetable panel;
     a plate with an id (and its text); a shelter at the kerb; stop markings on the
     road; a bus pictogram
   - **look-alike features:** a walking figure (pedestrian crossing); arrows (lane,
     direction, mandatory signs); a "P"; a wheelchair; a plain blue square; a street
     name plate; a red prohibition disc or warning triangle; a private-road,
     house-number or field plate; a pole at a narrow lane, dirt track, driveway or
     footpath (Cotral buses are coaches: no stop is there)
   - **design:** the Cotral sign's design (navy, or grey or washed out in poor
     light); whether the panel's text is readable at all

   **Code decides** (`confirmer.verdict`, since harness 0.12):
   - the Cotral logo with FERMATA or the Cotral design: confirmed, whatever else is
     in view (busy stops have road signs beside them);
   - otherwise any look-alike feature: not a stop;
   - otherwise a stop feature other than the bus pictogram and the plate: confirmed.
     **A bus pictogram alone is not enough** (bus-lane signs carry one,
     `GROUND_TRUTH/lookalikes/blu_signs.png`), **nor is a plate alone** (a house
     number "96" under a private-road sign was confirmed in 0.11.1);
   - otherwise the Cotral design with unreadable text: `cotral_sign_by_design`.

   **Second views** of a "could be a stop" close view are framed on the first view's
   sight line (0.6 to 1.6 times the estimated distance: a single view's distance is
   unreliable). A second view can confirm a candidate, never reject it: it may not
   show the object at all.

**What both calls see** (frozen, so it caches): the reference Cotral sign, and the
look-alikes in `GROUND_TRUTH/lookalikes/` (`blu_signs.png`: 50 blue Italian road
signs; `crossing.png`: the pedestrian crossing). More can be added, for example
crops from our own runs. Note: `blu_signs.png` carries a stock-photo watermark;
fine for local prompts, to replace before anything is published.

**Other stops nearby.** Every other GTFS stop within the search limits is shown as
"another stop, not this one". A confirmed sign within 15 m of one is accepted only if
its plate reads this stop's id; otherwise the search goes on. (The opposite-direction
twin is on the left of travel, so the side rule already excludes it.)

## 4. The data the search stands on

### 4.1 The bus's path, snapped to the roads (done)

GTFS shapes are coarse (median gap between points 133 m; 17% over 300 m), so a
straight chord cuts bends and can skip a loop. `cotral_maintenance/roadpath.py` snaps
the shape near the stop onto OSM roads (hidden Markov model, one-way rules for
buses), about 0.3 s per stop.

**On 502 verified stops** (`experiments/explore/route_paths.py`):

| | Raw shape | Snapped path |
|---|---|---|
| Verified position, median distance | 7.5 m | **6.9 m** |
| Within 10 m | 72% | **80%** |
| Right of travel | 86% | **88%** |

- 93% snap in one piece.
- **For 45% of stops the path strays more than 15 m from a straight line** within
  ±150 m: a straight road frame (version 1, the Clef explorer) is wrong half the time.
- **Loops or out-and-back stretches** within ±300 m for 11%; the stop is on one for 7%.
- **GTFS is on the wrong side of the path for 15%.**

The Shapes page shows raw shapes dashed and snapped paths solid, for 179 stops
flagged for a reason (§7).

### 4.2 Right of travel, at the stop's place in the trip

The stop is **always on the right of the direction of travel** (doors on the right,
Italy drives on the right). On an out-and-back stretch the same sidewalk is right
going in and left coming out: f13457 (VELLETRI | Carcere) looks 10 m on the left of
the nearest leg, and is on the right of the leg the bus drives. So:
- the search covers **the path from the previous stop to the next**, in travel order;
- **each pass is a leg** with its own right-hand sidewalk; both passes of a loop are
  searched;
- where several shapes serve the stop and their paths differ, the stop is on the
  right of every one of them; stretches where all agree weigh more.

Of the 52 stops left of the nearest leg by more than 3 m, 8 are near a loop like
f13457 and 13 are over 25 m from the path; the rest are to look at on the Shapes
page.

### 4.3 Where Street View has been

Panoramas along the path come from free metadata lookups, 2024 onwards only, each
placed on the path (metres along, leg, side, scan date). A stretch with no panorama
within 15 m is **unscanned**: no photo can show it. The explorer is told, and it's
reported in `unscanned`.

### 4.4 Positions and hints

**One OSM source: the local store** `data/osm/osm.sqlite3`, built by
`experiments/explore/build_osm_store.py` from Geofabrik's Central and Southern Italy
extracts (2026-11-07). 375,429 bus-drivable roads; 17,942 stop-like objects: 14,660
bus stops, 1,494 stop positions, 1,425 platforms, 220 public-transport shelters (like
node 9431511793 at f13457), 143 bus stations; areas and multipolygons at their
centre. **Checked:** every object of the former CSVs is in it, except 7 deleted from
OSM since the spreadsheet's export and 22 that are 36–40 km from any Cotral stop.
The CSVs and the id matching are gone.

**OSM first (2026-11-09).** OSM is the most accurate position source when an object can be
tied to the stop (`cotral_maintenance/osm_match.py`). Measured on the 504 verified stops, error
to the verified position:

| Match | Stops | Median | Their GTFS |
|---|---|---|---|
| `ref` lists the stop id (anywhere) | 135 | 6.9 m | 17.0 m |
| nearest stop-like object within 100 m of GTFS, closer to this stop than to any other Cotral stop | 132 | 9.9 m | 16.7 m |
| name alone (not used: worse than GTFS) | 12 | 33 m | 24.8 m |
| no match: GTFS | 225 | 31 m | |
| **all, OSM first** | 504 | **17.5 m** | 23.7 m |

Places adds nothing today: only 86 of 13,595 stops have it, and where it exists it usually
copies GTFS. Other OSM objects stay **hints**.

| Source | Role |
|---|---|
| OSM matched, else Places, else GTFS | **the start** (0 m): the opening sweep is taken there; the prior is the measured spread around it |
| The other sources | listed as less accurate positions |
| OSM stop-like objects on the right of the path, within 20 m of it | **hints** |
| Other GTFS stops | **"not this stop"** markers |

**Likelihood.** Where the stop probably is, per 4 m of right-hand sidewalk: the
measured spread around each starting position (§4.5), bumps at hints, more weight
where serving paths agree. The explorer sees it as "where the unlooked likelihood
is", to help it choose; it doesn't drive the search. The weights per source and per
OSM kind are measured on the verified stops before the first run (§7).

ATAC was tried and dropped (2026-11-06). OSM is ODbL: published positions derived
from it need attribution, and share-alike applies.

### 4.5 Where stops really are, relative to GTFS

On 489 verified stops, along the path: within 10 m for 38%, 10–25 m 22%, 25–50 m
20%, 50–100 m 14%, over 100 m 6%. **Symmetric:** of those moved 10 m or more, 158
are ahead and 145 behind.

### 4.6 Other scans

Any panorama can be photographed by id, whatever its date, but nothing lists earlier
captures: other drives turn up only where one is still the nearest panorama (another
lane, the other carriageway). Small-radius lookups across the road reach those.
**2024 onwards only**; captions show the date; a stop seen only in an older scan
carries that date and lower confidence; triangulate within one scan date only.

## 5. Computing the position

1. **Two or more marks from different panoramas of the same scan date:** sight lines
   crossed (least squares), with the leftover error.
2. **One mark:** the sight line cut by the right-hand sidewalk of that leg.
3. **No mark:** the panorama's position, flagged `panorama`.

A mark is a point the LLM clicks in a photo; code turns its x into a compass bearing
(from heading and fov) and its y into a rough distance (camera height and pitch,
ground plane). Before submitting, the explorer is reminded that a second view from
another panorama makes the position triangulated.

## 6. The harness

### 6.1 Who does what

| | Harness (code) | Explorer (LLM, the conversation) | Confirmer (LLM, fresh call) |
|---|---|---|---|
| Path, legs, side, panoramas, unscanned stretches | ✓ | | |
| Bookkeeping: what each part of the sidewalk has been seen as | ✓ (from the explorer's marks) | | |
| Likelihood, hints, "not this stop" | ✓ | | |
| Turning marks into positions | ✓ | | |
| Looking at photos, marking what's in them | | ✓ | |
| **Deciding where to look next, and how far to jump** | | ✓ | |
| Getting round obstructions | | ✓ | |
| The checklist on a candidate | | | ✓ |
| Deciding "confirmed" from the checklist | ✓ | | |
| Submitting | | ✓ (only a confirmed candidate) | |

### 6.2 The opening: two overview photos

Taken by the harness before the explorer's first turn, around the **start**: the best
starting position (OSM when matched, else Places, else GTFS) placed on the path.
1. **From a few metres back, facing forward:** from the panorama about 15 m before
   the start, looking along the path in the direction of travel.
2. **From a few metres ahead, facing backward:** from the panorama about 15 m after
   the start, looking back along the path.

Both are wide (fov about 100°) and turned slightly (about 15°) towards the right-hand
sidewalk of travel, which is on the right of photo 1 and on the left of photo 2.
Together they show the road both ways: what is near the start, how far the view
reaches, where the road bends, where parked cars or trees block it. **From these the
explorer decides which way to go and how far to jump.** "15 m" and "15°" are starting
values to tune on the test stops.

### 6.3 What the explorer is told at the start

- **The task and rules** (frozen): find a stop of this route; right-hand sidewalk of
  travel only; existence over branding; spot then confirm; 14 photos; no give-up;
  what the tools do; how positions along the path work.
- **The reference sign and the look-alikes** (frozen images).
- **The stop:** name, id.
- **The text map,** in metres along the path from the start (+ ahead in the direction
  of travel, − behind):
  - the search limits (halfway to the previous and next stops, wide enough for all
    starting positions)
  - the legs, and bends and junctions on them ("+40 m: the path turns right into Via
    X"; "+120 to +210 m: out-and-back into a square, second pass from +210 m")
  - starting positions and hints: "Places: +0 m"; "GTFS: −22 m, 6 m left of the path
    (GTFS is often on the wrong side)"; "OSM shelter: +18 m, right, 9 m from the path"
  - "not this stop" markers: "stop f1234 'X': −310 m, right"
  - panoramas: ranges and spacing per scan date ("2026-07: every 8–12 m from −180 to
    +240 m; 2024-05: −40 to +30 m, other carriageway"); unscanned stretches
- **The two opening photos,** each with its caption (§6.5).
- **The state** (§6.4).

### 6.4 The state, after every action

- photos left (of 14)
- the right-hand sidewalk per leg as ranges: `seen close` · `surveyed clear` ·
  `not looked at` · `hidden` (with why) · `unscanned`
- where the unlooked likelihood is ("62% of it is between −30 and +40 m")
- hints and candidates: not looked at / looked at / candidate / confirmed / rejected
  (with the checklist's reason)

### 6.5 Tools

Flat arguments only (small local models handle them best). Every argument is
validated; an invalid call gets an error with the reason, and the explorer tries
again (up to 3 times in a row, then the stop is `failed`).

| Tool | Cost | What it does |
|---|---|---|
| `look(from_m, toward, target_m, fov, pitch, leg, scan)` | 1 photo | Take a photo from the panorama nearest `from_m` on the path. `toward` is `forward` or `backward` (along the path, turned a little towards the right-hand sidewalk), `across` (straight at the right-hand sidewalk), or `target` (aim at the right-hand sidewalk at `target_m`: for angled views past an obstruction). `fov` 20–120 (default by `toward`), `pitch` optional (look higher over a van), `leg` for the second pass of a loop, `scan` a date to use another scan. The photo comes back with its caption: panorama, scan date, where it stands, which stretch of sidewalk is in view and where it lies in the frame. |
| `mark_candidate(photo, x, y, kind)` | free | Something worth confirming at that point: `sign`, `shelter`, `pole_with_panel`, `bench`, `road_marking`, `people_waiting`. Code places it on the sidewalk and returns its position ("candidate 2: +31 m, right"). |
| `mark_clear(photo, x, y)` | free | In a photo looking along the sidewalk: from the camera up to this point the right-hand sidewalk is clearly visible and holds nothing stop-like. That stretch becomes `surveyed clear`. **This is what lets the explorer jump.** |
| `mark_hidden(photo, x, y, reason)` | free | That part of the sidewalk can't be seen (`vehicle`, `vegetation`, `glare`, `blur`, `dirty_lens`, `dark`). It becomes `hidden`. |
| `confirm(candidate, from_m)` | 1 photo | A narrow photo of the candidate (from `from_m`, or the nearest panorama), checked by the fresh confirmer call (§3). Returns the photo, the checklist and the verdict. |
| `find_other_scans(at_m)` | free | Lookups across the road at that point; new panoramas from 2024 onwards are added to the map. |
| `show_map()` | free | The debug map as an image (§6.6) and the state as text. |
| `note(text)` | free | A plan or a reason, kept in the transcript. |
| `submit_found(candidate)` | — | Ends the search. Refused, with the reason, unless the candidate is confirmed and passes the "not this stop" rule. |

`seen close` is set by code: an `across` or `target` photo whose stretch lies within
the distance where a sign is large enough to recognise, and which the explorer
didn't mark hidden. A turn cap (40 tool calls) stops loops of free tools.

### 6.6 Debug map

After every action the harness draws the search on a map and saves it with the
transcript: the path and its legs with arrows; the right-hand sidewalk coloured by
state; starting positions, hints, candidates, "not this stop" markers; panoramas by
scan date; every photo as a view cone; marks and sight lines; unscanned stretches.
The explorer gets it on `show_map()`. The Explore page of the review app replays
every run step by step (built).

### 6.7 The conversation (Qwen3.8-27B on llama-server)

- `experiments/explore/qwen_server.sh`: llama.cpp `llama-server` with the Unsloth
  UD-Q2_K_XL GGUF (9.8 GB) and its vision projector; about 15 GB resident on the
  24 GB M5, about 60 tokens/s reading and 6 tokens/s writing (a 640 px photo is about
  400 tokens, 7 s). `experiments/explore/qwen_run.py` runs the loop.
- Points on photos on a 0-1000 grid (Qwen-VL's native scale; it located a sign within
  3 px). Photos go inside the tool results, labelled as the text calls them.
- Every turn is a constrained tool call (`tool_choice: required`); thinking at low
  effort (about 100 tokens a turn), kept in the history so each request only extends
  the cached prompt (the model's DeltaNet layers can't roll their state back).
- Two server slots of 48K tokens: the explorer and the confirmer each keep their own
  cached prompt. The whole history stays: every photo, call and result.

## 7. Measurements

Done: shape accuracy, side rule, along-path spread, OSM coverage, snapping
(§4). **Pending your verdicts:** the Shapes page (`./start.sh`, then `/shapes`): 179
stops, flagged as moved ≥ 50 m (118), left of the snapped path (52), far from it
(30), on a detour (35).

Before implementing (free or nearly):
1. **Likelihood weights:** per starting source and per OSM kind, how often it lies
   within 15 m of the verified position, and on which side of the path.
2. **Street View coverage along the snapped paths** of the test stops: how much is
   unscanned, especially loops.
3. **Other scans** along the test stretches: do several 2024+ dates exist?
4. **The confirmer alone,** on photos we have (the dry runs' photos, the f10923
   crossing sign) plus narrow photos of the test stops' verified positions: does the
   checklist accept real stops and reject look-alikes?
5. **The local model:** done for Qwen3.8-27B (§6.7): it runs, points accurately,
   about 30-40 s a turn.

## 8. Evaluation

**Test set:** the 21 stops with both a Places and a manual position (f9388 plus 20
drawn with seed 11; input error 0 m for 6, up to 230 m for f7824), plus f13457 (the
shelter, the out-and-back) and f10923 (the crossing sign).

**Metrics:** found rate; share under 10 m and 20 m; median output error against input
error; **false-found rate**; unscanned share on `not_found`; photos, model calls and
minutes per stop.

**Compared:**
- (a) the starting position unchanged
- (b) a fixed sweep around the start with the LLM only marking and confirming (a
  baseline, to measure what the explorer's own decisions add)
- (c) the full explorer

## 9. Reuse

- Done: `osm_store.py`, `roadpath.py` (snapping; `locate` for metres along and side),
  `routes.py` (services and shapes), the Explore and Shapes pages.
- `panoramas.py` (metadata), `streetview.py` (photos), `tiles.py` + `render.py` (the
  plate zoom: at most 5 tiles per stop, after a stop is found).
- Built for the dry runs: `cotral_maintenance/explorer/` (geometry, world, session, debug map), the MCP tool server and runner in `experiments/explore/` (`agent_server.py`, `agent_dry_run.py`); runs are replayed on the Explore page.
- `experiments/gemma/score_stops.py`: chat requests, image data URLs, validate and
  retry.
- New: the path frame with legs, the bookkeeping, the text map and state, the tools,
  the confirmer, triangulation.

## 10. Decisions

| Question | Decision |
|---|---|
| Explorer | An LLM (Qwen3.8-27B locally, bigger later; Haiku for dry runs). Clef and any other single-call model dropped for exploring, for good. |
| Context | Plan for 100K; every photo stays in the conversation. |
| Priority | Good first, fast later. |
| Who decides where to look | The LLM. The harness gives facts and bookkeeping, no programmatic jumps. |
| Opening | Two overview photos: from behind the start facing forward, from ahead facing backward. |
| Path | The shape snapped onto OSM roads, previous stop to next. |
| Side | Right of travel, per leg; both passes of a loop. |
| Finding | Spot, then confirm by a fresh LLM call with a checklist; code decides. A bus pictogram alone doesn't count. |
| OSM | One local store from Geofabrik; a matched object (by `ref`, else nearest) is the start; the others are hints. |
| Starting positions | OSM when matched, else Places, else GTFS. |
| Unscanned stretches | Reported, never searched. |
| Zoom | After found only; Map Tiles, at most 5 tiles. |
| Stopping | Only when found; otherwise 14 photos, then `not_found`. |
| Scans | 2024 onwards only. |

## 11. Pseudocode

### Once, before any stop
1. Build the OSM store from the Geofabrik extracts. Re-run when they're refreshed.
2. Read the GTFS: for every stop, the shapes of the trips serving it, with the stop
   before and after.
3. Read the starting positions (Places, GTFS) and, in evaluation runs, the verified
   positions.
4. Load the frozen material: task text, reference sign, look-alikes, likelihood
   weights.

### For each stop

**A. Lay out the path**
1. Snap each serving shape near the stop onto the roads.
2. On the main path, place the previous and next stop; keep the stretch between them,
   in travel order. Where the bus passes a place twice, keep both passes as separate
   legs.
3. If nothing snaps: the road route between the previous and next stop; failing that,
   a straight line.
4. Place the start (OSM when matched, else Places, else GTFS) on the path: 0 m. Set the limits: halfway to
   the previous and next stops, wide enough for every starting position.
5. Note where all serving paths agree, and the bends and junctions along the path.

**B. Put everything on the path**
1. Place the starting positions, the OSM hints (within 20 m of the path, on the
   right) and the "not this stop" markers: metres along, leg, side, distance.
2. Find the panoramas along the path (free, 2024 onwards), plus a little to each side
   for other drives. Place each on the path. Mark stretches with none within 15 m as
   unscanned.
3. No panorama at all: `no_imagery`. Stop.
4. Cut the right-hand sidewalk of each leg into 4 m cells, `not looked at` or
   `unscanned`, and give each its likelihood.

**C. Open**
1. Take the two overview photos: from about 15 m behind the start facing forward,
   from about 15 m ahead facing backward, both wide and turned a little towards the
   right-hand sidewalk.
2. Start the conversation: task and rules, reference and look-alikes, the stop, the
   text map, the two photos with captions, the state.

**D. Repeat until the search ends**
1. Ask the explorer for one tool call. If invalid, say why and ask again (3 times in
   a row at most, then `failed`).
2. Carry it out:
   - **look:** refuse if 14 photos are used. Pick the panorama on the right leg
     nearest `from_m` (from the requested scan if any), set heading, fov and pitch,
     take the photo (or reuse it from disk), and send it with its caption. An
     `across` or `target` photo marks its nearby stretch `seen close`.
   - **mark_candidate:** place the point on the sidewalk; add a candidate; return its
     position.
   - **mark_clear:** place the point on the sidewalk; the stretch from the camera to
     there becomes `surveyed clear` (unless already seen close).
   - **mark_hidden:** that stretch becomes `hidden`, with the reason.
   - **confirm:** refuse if 14 photos are used. Take a narrow photo of the candidate,
     send it, the reference sign and the look-alikes to a fresh LLM call with the
     checklist; apply the rule; mark the candidate confirmed or rejected; return the
     photo, the answers and the verdict. A confirmed candidate gets its position
     from its marks.
   - **find_other_scans:** look up across the road; add new panoramas.
   - **show_map:** draw the map and return it with the state.
   - **note:** record it.
   - **submit_found:** check the candidate is confirmed and passes "not this stop".
     If so, the search ends as `found`; if not, return why.
3. Send the updated state.
4. Save the transcript and the debug map.
5. **14 photos used:** a confirmed candidate may still be submitted; otherwise
   `not_found`. **Turn cap:** `not_found`, reason "turn cap".

**E. The answer**
1. Position from the confirmed candidate's marks: crossing sight lines if two
   panoramas of one scan saw it, else the sight line cut by the sidewalk.
2. Zoom on the plate with Map Tiles (at most 5 tiles) to read the stop id.
3. Record status, position and basis, evidence, scan date, plate text, confidence,
   nearest source, unscanned stretches with their likelihood, photos, model calls,
   time.
4. Save transcript, photos, maps.

### After a run
One row per stop (result, starting positions, verified position when known); the
metrics of §8 per variant.

## Verification (when we implement)

- Unit tests with fakes: legs and side on an out-and-back stretch (f13457); placing a
  clicked point on the sidewalk; bookkeeping from marks; the opening photos' panoramas
  and headings on a bent path; the checklist rule (a bus-lane sign rejected, a stop
  sign accepted); "not this stop"; unscanned stretches; budgets and the stopping
  rule; flat-argument validation and retries; triangulation within one scan date;
  transcripts that only grow, images only in user messages.
- Then the confirmer alone (§7.4), a smoke run on f9388 and f13457, then the test
  set, variants (a), (b), (c).
