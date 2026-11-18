import pytest

from cotral_review.api import create_app
from fastapi.testclient import TestClient

from .conftest import IDS, JPEG


def post(client, left="a1", right="b2", winner="a1", **extra):
    return client.post("/api/judgments", json={"left": left, "right": right, "winner": winner, **extra})


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_catalog(client):
    body = client.get("/api/catalog").json()
    keys = [c["key"] for c in body["categories"]]
    assert keys == ["shelter", "seating", "signage", "lighting", "waiting_area", "accessibility",
                    "requires_maintenance", "stop_visible"]
    kinds = {c["key"]: c["kind"] for c in body["categories"]}
    assert kinds["stop_visible"] == "probability" and kinds["shelter"] == "level"
    labels = {c["key"]: c["label"] for c in body["categories"]}
    assert labels["stop_visible"] == "Stop visible" and labels["requires_maintenance"] == "Overall maintenance"
    assert all(c["label"] and c["description"] for c in body["categories"])
    assert body["models"] == [{"key": "imajev", "label": "imajev-4b",
                               "description": "Expected level under Imajev's calibrated probabilities"}]


def test_stops_are_the_scored_ones_in_run_order(client):
    stops = client.get("/api/stops").json()
    assert [s["stop_id"] for s in stops] == IDS  # not the unscored, not-found or no-imagery stops
    first = stops[0]
    assert first["scores"] == {"imajev": {"shelter": 1.0, "seating": 1.0, "signage": 1.0, "lighting": 1.0,
                                          "waiting_area": 1.0, "accessibility": 1.0, "requires_maintenance": 1.0,
                                          "stop_visible": 0.9}}
    assert stops[3]["scores"]["imajev"]["requires_maintenance"] == 4.0
    assert first["evidence"]["imajev"]["shelter"] == "unknown 23%, confidence 0.41"
    assert first["evidence"]["imajev"]["signage"] == "abstained, unknown 23%, confidence 0.41"
    assert client.get("/api/stops/b2").json()["name"] == "Stop b2"


def test_stop_position_is_the_found_one_then_the_start_then_gtfs(run_dir, settings):
    from cotral_maintenance.runstore import RunStore

    with RunStore(run_dir) as store:
        store.put_exploration(store.exploration("a1") | {"lat": None, "lon": None, "stop_photos": []}, [], [])
        for stop_id in ("a1", "e5", "f6"):  # scored without a found position
            store.put_score({"stop_id": stop_id, "photos": [], "scorer": {"model": "m"}, "answers": {}, "seconds": 1.0})
        store.put_start({"stop_id": "f6", "source": "gtfs", "lat": 41.5, "lon": 12.5})
    client = TestClient(create_app(settings))
    by_id = {s["stop_id"]: s for s in client.get("/api/stops").json()}
    assert (by_id["a1"]["lat"], by_id["a1"]["lon"]) == (41.0, 12.0001)  # the start (OSM), not found
    assert (by_id["f6"]["lat"], by_id["f6"]["lon"]) == (41.5, 12.5)
    assert (by_id["e5"]["lat"], by_id["e5"]["lon"]) == (41.0, 12.0)  # GTFS
    assert by_id["b2"]["lat"] == pytest.approx(41.0011)  # found


def test_photos_come_from_the_stop_photos(client):
    stop = client.get("/api/stops/a1").json()
    assert stop["imagery_date"] == "2025-06"
    first, second = stop["photos"]
    assert (first["view"], first["description"]) == ("stop_photo_1", "From the panorama that confirmed the stop")
    assert second["description"] == "From about 12 m before the stop"
    assert (first["heading"], second["heading"], first["copyright"], first["distance_m"]) == (90.0, 70.0, "© Google", None)
    assert first["url"].startswith("/api/stops/a1/photos/") and first["url"].endswith(".jpg")


def test_unknown_stop_is_404(client):
    response = client.get("/api/stops/nope")
    assert response.status_code == 404 and "detail" in response.json()
    assert client.get("/api/stops/g7").status_code == 404  # in the run, but not scored


def test_photo(client):
    url = client.get("/api/stops/a1").json()["photos"][0]["url"]
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "max-age" in response.headers["cache-control"]
    assert response.content.startswith(JPEG)


def test_photo_rejects_other_stops_photos_and_traversal(client, run_dir):
    sha = client.get("/api/stops/a1").json()["photos"][0]["url"].rsplit("/", 1)[1]
    other = client.get("/api/stops/b2").json()["photos"][0]["url"].rsplit("/", 1)[1]
    search = next((run_dir / "media").rglob("*.jpg")).name  # some media of the run that is nobody's stop photo
    for path in [
        f"/api/stops/a1/photos/{other}",                 # a photo of another stop
        f"/api/stops/nope/photos/{sha}",
        f"/api/stops/..%2Fa1/photos/{sha}",
        f"/api/stops/a1/photos/..%2F..%2Frun.sqlite",
        f"/api/stops/a1/photos/{sha[:-4]}",             # no extension
        f"/api/stops/a1/photos/{sha[:2].upper()}{sha[2:]}",  # not lower-case hex
        f"/api/stops/a1/photos/{'0' * 64}.jpg",
        f"/api/stops/a1/photos/{search.replace('.jpg', '')}.png",
    ]:
        assert client.get(path).status_code == 404, path


def test_missing_media_file_is_404(client, run_dir):
    url = client.get("/api/stops/a1").json()["photos"][0]["url"]
    sha = url.rsplit("/", 1)[1].removesuffix(".jpg")
    (run_dir / "media" / sha[:2] / f"{sha}.jpg").unlink()
    assert client.get(url).status_code == 404


def test_next_pair_hides_scores(client):
    body = client.get("/api/pairs/next").json()
    pair = body["pair"]
    assert pair["left"]["stop_id"] != pair["right"]["stop_id"]
    for side in pair.values():
        assert "scores" not in side and "evidence" not in side and side["photos"]
    assert body["progress"] == {"judged": 0, "skipped": 0, "remaining": 6}


def test_next_pair_left_right_order_varies(client):
    firsts = {client.get("/api/pairs/next").json()["pair"]["left"]["stop_id"] for _ in range(40)}
    assert len(firsts) > 1


def test_judgment_roundtrip(client):
    response = post(client, rater="Maruf", decision_ms=1234)
    assert response.status_code == 201
    body = response.json()
    j = body["judgment"]
    assert (j["left"], j["right"], j["winner"], j["loser"], j["rater"], j["decision_ms"]) == (
        "a1", "b2", "a1", "b2", "Maruf", 1234)
    assert j["created_at"].endswith("+00:00") and j["id"]
    assert body["left"]["scores"]["imajev"] and body["right"]["stop_id"] == "b2"  # scores revealed after judging
    assert body["progress"] == {"judged": 1, "skipped": 0, "remaining": 5}
    assert client.get("/api/judgments").json() == [j]
    assert client.get("/api/judgments/progress").json() == body["progress"]


def test_skip_counts_as_skipped(client):
    j = post(client, winner=None).json()["judgment"]
    assert j["winner"] is None and j["loser"] is None
    assert client.get("/api/judgments/progress").json() == {"judged": 1, "skipped": 1, "remaining": 5}


def test_judgments_oldest_first(client):
    post(client, "a1", "b2")
    post(client, "c3", "d4", "d4")
    assert [(j["left"], j["winner"]) for j in client.get("/api/judgments").json()] == [("a1", "a1"), ("c3", "d4")]


def test_duplicate_pair_either_order_is_409(client):
    assert post(client).status_code == 201
    assert post(client).status_code == 409
    assert post(client, left="b2", right="a1", winner="a1").status_code == 409
    assert client.get("/api/judgments/progress").json()["judged"] == 1


def test_unknown_stop_is_404_on_post(client):
    assert post(client, right="zzz").status_code == 404
    assert post(client, left="zzz", winner=None).status_code == 404


@pytest.mark.parametrize("body", [
    {"left": "a1", "right": "a1", "winner": "a1"},
    {"left": "a1", "right": "b2", "winner": "c3"},
    {"left": "a1", "right": "b2"},
    {"left": "a1"},
    {"left": "a1", "right": "b2", "winner": "a1", "decision_ms": "slow"},
    {"left": "a1", "right": "b2", "winner": "a1", "decision_ms": -5},
    {"left": 1, "right": "b2", "winner": None},
])
def test_invalid_body_is_422(client, body):
    assert client.post("/api/judgments", json=body).status_code == 422
    assert client.get("/api/judgments").json() == []


def test_next_pair_never_repeats_until_done_even_across_reopen(settings):
    seen = set()
    client = TestClient(create_app(settings))
    for n in range(6):
        if n == 3:
            client = TestClient(create_app(settings))  # reopened database
        body = client.get("/api/pairs/next").json()
        assert body["pair"] is not None
        left, right = body["pair"]["left"]["stop_id"], body["pair"]["right"]["stop_id"]
        key = frozenset((left, right))
        assert key not in seen
        seen.add(key)
        assert post(client, left, right, left).status_code == 201
    done = client.get("/api/pairs/next").json()
    assert done["pair"] is None
    assert done["progress"] == {"judged": 6, "skipped": 0, "remaining": 0}


def test_unknown_api_path_is_404_not_frontend(client):
    assert client.get("/api/nope").status_code == 404


def test_openapi_documents_contract(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert {"/api/catalog", "/api/stops", "/api/pairs/next", "/api/judgments"} <= set(paths)


def test_no_frontend_message(client):
    response = client.get("/")
    assert response.status_code == 200 and "npm run" in response.text


def test_frontend_served_with_spa_fallback(settings):
    dist = settings.frontend_dist
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    client = TestClient(create_app(settings))
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/stops/a1/compare").text == "<html>app</html>"  # client-side route
    assert client.get("/../../etc/passwd").text == "<html>app</html>"
    assert client.get("/api/nope").status_code == 404
