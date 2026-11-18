"""Check that Imajev on llama.cpp (GGUF + the readout applied here) answers like Imajev's reference server.

The remote profile scores with a GGUF on llama-server: the final hidden state comes from the
server's /embedding endpoint and the trained readout is applied in cotral_maintenance/scorer. This
compares it, question by question, with the reference MLX (or PyTorch) server on the same photos
and questions. Both servers must be running:

    # reference: scripts/setup_imajev_mlx.sh, then (from $IMAJEV_HOME) the command it prints (port 8765)
    # llama.cpp: llama-server -m imajev-4b-Q8_0.gguf --mmproj imajev-4b-mmproj-f16.gguf --port 8090 \
    #                --embeddings --pooling last -c 8192 -np 2 -ngl 99
    uv run python scripts/check_imajev_parity.py PHOTO.jpg [PHOTO2.jpg] [--run runs/RUN --stops 5]

Prints, per question, both answers and their difference. Expect small differences (quantization,
image preprocessing); a large one on many questions means the prompt, the template or the hidden
state is not what the readout was trained on.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cotral_maintenance.runstore import RunStore  # noqa: E402
from cotral_maintenance.scorer import questions as Q  # noqa: E402
from cotral_maintenance.scorer.backends import LlamaCppReadout, SystemOne  # noqa: E402
from cotral_maintenance.scorer.imajev import Calibration, Engine  # noqa: E402
from cotral_maintenance.servers import fetch  # noqa: E402
from cotral_maintenance.settings import Paths, load_profile  # noqa: E402


def value(answer: dict) -> float:
    return answer["score"] if answer["type"] == "score" else answer["noul"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("photos", nargs="*", type=Path)
    parser.add_argument("--run", type=Path, help="score the stop photos of this run's found stops instead")
    parser.add_argument("--stops", type=int, default=5)
    parser.add_argument("--reference", default="http://127.0.0.1:8765")
    parser.add_argument("--llamacpp", default="http://127.0.0.1:8090")
    parser.add_argument("--profile", default="remote", help="where the readout and calibration files are pinned")
    args = parser.parse_args()

    paths = Paths.from_env()
    spec = load_profile(paths, args.profile).scorer
    engine = Engine(Calibration.load(fetch(spec.readout["calibration"], paths.models)), rotations=4)
    gguf = LlamaCppReadout(args.llamacpp, fetch(spec.readout["readout"], paths.models), engine, {}, parallel=2)
    reference = SystemOne(args.reference, {})

    cases: list[tuple[str, str, str | None, list[bytes]]] = []
    if args.run:
        with RunStore(args.run) as run:
            for r in run.query("SELECT e.stop_id, s.name, e.evidence, e.stop_photos FROM explorations e "
                               "JOIN stops s USING (stop_id) WHERE e.status = 'found' LIMIT ?", (args.stops,)):
                import json

                shas = json.loads(r["stop_photos"])[:2]
                cases.append((r["stop_id"], r["name"], r["evidence"], [run.media(s).read_bytes() for s in shas]))
    if args.photos:
        cases.append(("files", "test stop", "cotral_sign", [p.read_bytes() for p in args.photos[:2]]))
    if not cases:
        parser.error("give photos or --run")

    worst = 0.0
    for label, name, evidence, photos in cases:
        state = Q.state(name, evidence, len(photos))
        a = reference.answer(Q.questions(), state, photos)
        b = gguf.answer(Q.questions(), state, photos)
        print(f"\n{label} ({len(photos)} photos)        reference   llama.cpp    diff   unknown ref / llama.cpp")
        for q in Q.questions():
            va, vb = value(a[q.name]), value(b[q.name])
            scale = 4.0 if q.type == "score" else 1.0
            worst = max(worst, abs(va - vb) / scale)
            print(f"  {q.name:22s} {va:9.3f} {vb:11.3f} {vb - va:+8.3f}   "
                  f"{a[q.name]['unknown_probability']:.2f} / {b[q.name]['unknown_probability']:.2f}")
    print(f"\nlargest difference, as a share of each question's range: {worst:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
