import json
import random
import sqlite3
import threading

import pytest

from cotral_review.__main__ import export, main, read_jsonl
from cotral_review.judgments import DuplicatePair, JudgmentRepository
from cotral_review.pairs import next_pair, remaining


def test_reopen_keeps_judgments_and_enforces_uniqueness(tmp_path):
    path = tmp_path / "sub" / "j.sqlite3"
    JudgmentRepository(path).add("a", "b", "a")
    repo = JudgmentRepository(path)
    assert repo.pairs() == {("a", "b")}
    with pytest.raises(DuplicatePair):
        repo.add("b", "a", None)


def test_database_itself_rejects_duplicate_pair(tmp_path):
    path = tmp_path / "j.sqlite3"
    JudgmentRepository(path).add("a", "b", None)
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO judgments VALUES ('x', 't', 'b', 'a', 'a', 'b', NULL, NULL, NULL, NULL)")
    with pytest.raises(sqlite3.IntegrityError):  # pair must be normalised
        conn.execute("INSERT INTO judgments VALUES ('y', 't', 'c', 'd', 'd', 'c', NULL, NULL, NULL, NULL)")


def test_schema_version_and_wal(tmp_path):
    path = tmp_path / "j.sqlite3"
    JudgmentRepository(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "j.sqlite3"
    sqlite3.connect(path).execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError):
        JudgmentRepository(path)


def test_concurrent_adds_from_threads(tmp_path):
    repo = JudgmentRepository(tmp_path / "j.sqlite3")
    errors = []

    def work(i: int) -> None:
        try:
            repo.add(f"s{i:02d}", f"t{i:02d}", None)
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and repo.counts() == (20, 20)


def test_pair_selection_enumerated_and_rejection_sampling():
    ids = [f"s{i}" for i in range(10)]
    judged = {(a, b) for a in ids for b in ids if a < b}
    assert next_pair(ids, judged, random.Random(0)) is None
    judged.discard(("s3", "s7"))
    assert set(next_pair(ids, judged, random.Random(0), enumerate_limit=5)) == {"s3", "s7"}
    assert set(next_pair(ids, judged, random.Random(0))) == {"s3", "s7"}
    assert next_pair(["only"], set(), random.Random(0)) is None


def test_rejection_sampling_avoids_judged_pairs():
    ids = [f"s{i}" for i in range(30)]
    judged = {(a, b) for a in ids for b in ids if a < b and (a, b) != ("s1", "s2")}
    rng = random.Random(3)
    for _ in range(5):
        assert set(next_pair(ids, judged, rng, enumerate_limit=10)) == {"s1", "s2"}


def test_remaining_ignores_judgments_of_stops_no_longer_present():
    assert remaining(["a", "b", "c"], {("a", "b"), ("a", "gone")}) == 2


def test_import_is_idempotent_and_export_roundtrips(tmp_path, capsys):
    source = tmp_path / "old.jsonl"
    records = [
        {"id": "1", "created_at": "2026-01-01T00:00:00+00:00", "left": "b", "right": "a", "winner": "a",
         "loser": "b", "rater": "M", "decision_ms": 10},
        {"id": "2", "created_at": "2026-01-02T00:00:00+00:00", "left": "a", "right": "c", "winner": None,
         "loser": None, "rater": None, "decision_ms": None},
        {"id": "3", "created_at": "2026-01-03T00:00:00+00:00", "left": "c", "right": "a", "winner": "c",
         "loser": "a", "rater": None, "decision_ms": None},  # same pair as 2: skipped
    ]
    source.write_text("\n".join(json.dumps(r) for r in records) + "\n\n")
    db = str(tmp_path / "j.sqlite3")
    assert main(["import-jsonl", str(source), "--database", db]) == 0
    assert main(["import-jsonl", str(source), "--database", db]) == 0
    repo = JudgmentRepository(tmp_path / "j.sqlite3")
    assert [j.id for j in repo.list()] == ["1", "2"]
    assert repo.list()[0].loser == "b" and repo.counts() == (2, 1)

    out = tmp_path / "out.jsonl"
    main(["export", "--format", "jsonl", "--out", str(out), "--database", db])
    assert read_jsonl(out) == repo.list()

    csv_out = tmp_path / "out.csv"
    main(["export", "--format", "csv", "--out", str(csv_out), "--database", db])
    lines = csv_out.read_text().splitlines()
    assert lines[0] == "id,created_at,left,right,winner,loser,rater,decision_ms"
    assert lines[1] == "1,2026-01-01T00:00:00+00:00,b,a,a,b,M,10"

    main(["export", "--database", db])
    assert capsys.readouterr().out.startswith("id,created_at")


def test_export_to_stream(tmp_path):
    import io

    repo = JudgmentRepository(tmp_path / "j.sqlite3")
    repo.add("a", "b", "b")
    buffer = io.StringIO()
    assert export(repo, "jsonl", buffer) == 1
    assert json.loads(buffer.getvalue())["winner"] == "b"
