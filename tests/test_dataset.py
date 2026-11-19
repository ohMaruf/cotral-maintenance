import hashlib
import zipfile

import pytest

from cotral_maintenance import dataset as D
from cotral_maintenance.versions import fingerprint, ingest_detail

GTFS = {name: f"{name} rows\n" for name in D.GTFS_FILES}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_zip(path, folder=""):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in GTFS.items():
            z.writestr(folder + name, text)
    return path


def manifest(root, extra=""):
    zip_bytes = make_zip(root / "feed.zip").read_bytes()
    (root / "sign.png").write_bytes(b"sign")
    (root / "dataset.toml").write_text(f'''name = "test"
[[source]]
role = "gtfs"
file = "feed.zip"
sha256 = "{sha(zip_bytes)}"
[[source]]
role = "sign"
file = "sign.png"
sha256 = "{sha(b"sign")}"
{extra}''')
    return D.Dataset.load(root / "dataset.toml")


def osm_source(data: bytes, url="http://example.test/x.osm.pbf"):
    return f'''[[source]]
role = "osm"
file = "osm/x.osm.pbf"
url = "{url}"
sha256 = "{sha(data)}"
retrieved = "2026-11-07"
'''


def test_states_of_the_files(tmp_path):
    ds = manifest(tmp_path, osm_source(b"pbf"))
    assert dict((s.file, st) for s, st in ds.check()) == {"feed.zip": "ok", "sign.png": "ok", "osm/x.osm.pbf": "missing"}
    (tmp_path / "osm").mkdir()
    (tmp_path / "osm/x.osm.pbf").write_bytes(D.LFS_POINTER + b"\noid sha256:abc\n")
    assert ds.of("osm")[0].state() == "lfs-pointer"
    (tmp_path / "osm/x.osm.pbf").write_bytes(b"other")
    assert ds.of("osm")[0].state() == "mismatch"
    assert ds.sign == tmp_path / "sign.png" and ds.of("osm")[0].info["retrieved"] == "2026-11-07"
    assert ds.identity() == {"name": "test", "sources": {s.file: s.sha256 for s in ds.sources}}


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.data


def test_fetch_downloads_what_is_missing_and_refuses_other_bytes(tmp_path, monkeypatch):
    ds = manifest(tmp_path, osm_source(b"pinned"))
    monkeypatch.setattr(D.requests, "get", lambda url, **kw: FakeResponse(b"latest moved on"))
    with pytest.raises(D.DatasetError, match="its URL serves other bytes"):
        D.fetch(ds, tmp_path / "gtfs")
    assert not (tmp_path / "osm/x.osm.pbf").exists()
    monkeypatch.setattr(D.requests, "get", lambda url, **kw: FakeResponse(b"pinned"))
    report = D.fetch(ds, tmp_path / "gtfs")
    assert report["osm/x.osm.pbf"] == "ok" and report["gtfs_dir"] == "unzipped"
    assert sorted(p.name for p in (tmp_path / "gtfs").iterdir()) == sorted(D.GTFS_FILES)


def test_a_bad_manifest_is_explained(tmp_path):
    (tmp_path / "dataset.toml").write_text('[[source]]\nrole = "gtfs"\nfile = "a.zip"\n')
    with pytest.raises(D.DatasetError, match="lacks sha256"):
        D.Dataset.load(tmp_path / "dataset.toml")
    with pytest.raises(D.DatasetError, match="no dataset manifest"):
        D.Dataset.load(tmp_path / "nope.toml")


def test_the_gtfs_is_unzipped_flat_once_and_never_replaced(tmp_path):
    nested = make_zip(tmp_path / "nested.zip", folder="feed/")
    out = tmp_path / "GTFS"
    assert D.unzip_gtfs(nested, out) == "unzipped" and (out / "stops.txt").read_text() == GTFS["stops.txt"]
    assert D.unzip_gtfs(nested, out) == "kept"
    (out / "stops.txt").write_text("another feed\n")
    assert D.unzip_gtfs(nested, out).startswith("kept, differs")
    assert (out / "stops.txt").read_text() == "another feed\n"


def test_the_ingest_version_depends_on_what_the_store_was_built_from_not_when():
    meta = {"build_version": "2", "extracts_sha256": "a,b", "region": "41,11,42,14", "built_at": "2026-11-07"}
    same = {**meta, "built_at": "2027-01-01", "extracts": "renamed.pbf"}
    other = {**meta, "extracts_sha256": "a,c"}
    assert fingerprint(ingest_detail(meta, "g")) == fingerprint(ingest_detail(same, "g"))
    assert fingerprint(ingest_detail(meta, "g")) != fingerprint(ingest_detail(other, "g"))
