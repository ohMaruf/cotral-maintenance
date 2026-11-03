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
                    "requires_maintenance", "classifiable"]
    kinds = {c["key"]: c["kind"] for c in body["categories"]}
    assert kinds["classifiable"] == "probability" and kinds["shelter"] == "level"
    assert all(c["label"] and c["description"] for c in body["categories"])
    assert [m["key"] for m in body["models"]] == ["clef", "gemma"]


def test_stops_listing_and_detail(client):
    stops = client.get("/api/stops").json()
    assert [s["stop_id"] for s in stops] == IDS
    first = stops[0]
    assert first["scores"]["clef"]["shelter"] == 1.0
    assert first["evidence"]["gemma"] == {"shelter": "shelter of a1", "classifiable": "sign seen"}
    assert "gemma" not in stops[3]["scores"]  # a model may be missing for a stop
    assert first["photos"] == [{
        "view": "sweep_1", "description": "About 24 m before the mapped stop position",
        "url": "/api/stops/a1/photos/sweep_1_640x640.jpg", "distance_m": 24.0, "heading": 90.0,
        "copyright": "© Google",
    }]
    assert client.get("/api/stops/b2").json()["name"] == "Stop b2"


def test_unknown_stop_is_404(client):
    response = client.get("/api/stops/nope")
    assert response.status_code == 404 and "detail" in response.json()


def test_photo(client):
    response = client.get("/api/stops/a1/photos/sweep_1_640x640.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "max-age" in response.headers["cache-control"]
    assert response.content == JPEG


@pytest.mark.parametrize("path", [
    "/api/stops/a1/photos/unlisted.jpg",             # on disk but not in the manifest
    "/api/stops/a1/photos/stop.json",
    "/api/stops/a1/photos/..%2Fb2%2Fsweep_1_640x640.jpg",
    "/api/stops/a1/photos/%2e%2e%2f%2e%2e%2fclef.csv",
    "/api/stops/..%2Fa1/photos/sweep_1_640x640.jpg",
    "/api/stops/nope/photos/sweep_1_640x640.jpg",
])
def test_photo_rejects_unlisted_and_traversal(client, path):
    assert client.get(path).status_code == 404


def test_photo_symlink_escape_is_blocked(settings, tmp_path):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"secret")
    link = settings.images_dir / "a1" / "sweep_1_640x640.jpg"
    link.unlink()
    link.symlink_to(secret)
    assert TestClient(create_app(settings)).get("/api/stops/a1/photos/sweep_1_640x640.jpg").status_code == 404


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
    assert body["left"]["scores"]["clef"] and body["right"]["stop_id"] == "b2"  # scores revealed after judging
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
