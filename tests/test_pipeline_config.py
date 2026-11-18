import threading

import pytest

from cotral_maintenance.caches import BudgetExhausted, MetadataCache, UsageLedger, key_id
from cotral_maintenance.errors import ConfigError, NoImageryError
from cotral_maintenance.explorer.llm import ChatClient
from cotral_maintenance.models import PanoMetadata
from cotral_maintenance.servers import _expand
from cotral_maintenance.settings import ROOT, Paths, ServerSpec, load_profile


def paths_with(tmp_path, text):
    (tmp_path / "profiles.toml").write_text(text)
    p = Paths.from_env()
    return Paths(**{**p.__dict__, "profiles": tmp_path / "profiles.toml"})


def test_shipped_profiles_load():
    paths = Paths.from_env()
    for name in ("remote", "local-smoke", "local-gguf"):
        profile = load_profile(paths, name)
        assert profile.explorer.dialect in ("llamacpp", "strict")
        assert profile.scorer.dialect in ("llamacpp-readout", "systemone")
    local = load_profile(paths, "local-gguf")
    assert local.explorer.concurrency == 1 and local.explorer.dialect == "llamacpp"  # inherited, then overridden
    assert local.scorer.server.files["model"].file.endswith("Q4_K_M.gguf")
    assert local.scorer.server.files["mmproj"].file == "imajev-4b-mmproj-f16.gguf"


def test_profile_errors_are_explained(tmp_path):
    paths = paths_with(tmp_path, '[profiles.a]\ninherit = "b"\n[profiles.b]\ninherit = "a"\n')
    with pytest.raises(ConfigError, match="loops"):
        load_profile(paths, "a")
    with pytest.raises(ConfigError, match="no profile"):
        load_profile(paths, "zzz")


def test_server_arguments_are_expanded(tmp_path, monkeypatch):
    spec = ServerSpec(kind="llama-server", port=9001)
    monkeypatch.setenv("IMAJEV_HOME", "/opt/imajev")
    assert _expand("-m {file:model} --port {port} {env:IMAJEV_HOME}/x", spec, {"model": tmp_path / "m.gguf"}) == \
        f"-m {tmp_path / 'm.gguf'} --port 9001 /opt/imajev/x"
    monkeypatch.delenv("IMAJEV_HOME")
    with pytest.raises(ConfigError):
        _expand("{env:IMAJEV_HOME}", spec, {})


def test_ledger_reserves_the_worst_case_and_settles_the_real_cost(tmp_path):
    ledger = UsageLedger(tmp_path / "u.sqlite", {"static": 30})
    k = key_id("secret")
    assert "secret" not in k
    r1 = ledger.reserve(k, {"static": 22})
    with pytest.raises(BudgetExhausted):
        ledger.reserve(k, {"static": 22})  # 22 reserved of 30: another stop could go over
    ledger.settle(r1, {"static": 5})
    assert ledger.used(k)["static"] == 5
    assert ledger.remaining(k)["static"] == 25
    ledger.reserve(k, {"static": 22})


def test_metadata_cache_remembers_misses_and_is_thread_safe(tmp_path):
    calls = []

    def lookup(lat, lon, radius):
        calls.append((lat, lon))
        if lat > 50:
            raise NoImageryError("none")
        return PanoMetadata("p1", lat, lon, "2025-01", "Google")

    cache = MetadataCache(tmp_path / "m.sqlite", lookup)
    threads = [threading.Thread(target=cache.get, args=(41.9, 12.5, 15)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cache.get(41.9, 12.5, 15).pano_id == "p1"
    assert cache.get(60.0, 12.5, 15) is None and cache.get(60.0, 12.5, 15) is None
    assert calls.count((60.0, 12.5)) == 1


class FakeHttp:
    def __init__(self):
        self.bodies = []

    def post(self, url, json, timeout):
        self.bodies.append(json)

        class R:
            status_code = 200

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "done"}}]}

        return R()


def test_strict_dialect_sends_only_standard_fields():
    http = FakeHttp()
    client = ChatClient("http://x", "gemma", "strict", {"temperature": 1.0, "min_p": 0.0, "top_k": 64},
                        {"reasoning_effort": "low"}, 100, http)
    client.complete([{"role": "user", "content": "hi"}], [{"type": "function"}], slot=3, seed=1)
    body = http.bodies[0]
    assert body["tool_choice"] == "auto"
    assert not {"id_slot", "cache_prompt", "chat_template_kwargs", "min_p"} & set(body)
    assert body["top_k"] == 64


def test_llamacpp_dialect_pins_slots_and_forces_a_call():
    http = FakeHttp()
    client = ChatClient("http://x", "qwen", "llamacpp", {"temperature": 1.0}, {"reasoning_effort": "low"}, 100, http)
    client.complete([], [{"type": "function"}], slot=3, seed=1)
    body = http.bodies[0]
    assert body["tool_choice"] == "required" and body["id_slot"] == 3 and body["cache_prompt"] is True
    assert body["chat_template_kwargs"] == {"reasoning_effort": "low"}


def test_explorer_prompt_ships_with_the_package():
    assert (ROOT / "cotral_maintenance" / "explorer" / "prompt.md").is_file()
