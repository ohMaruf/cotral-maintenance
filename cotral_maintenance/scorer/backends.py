"""Where Imajev runs. Every backend takes the same questions and photos and returns Jev answers.

- `LlamaCppReadout`: a GGUF of Imajev on llama-server (CUDA on the GPU server, Metal on a Mac),
  started with `--embeddings --pooling last`. The server returns the final hidden state at the
  answer position; the trained readout (`decision_readout.safetensors`, from the adapter repo:
  the GGUF does not carry it) turns it into option logits here. All prompts of a stop are sent
  concurrently, so the server's parallel slots stay busy.
- `SystemOne`: Imajev's own reference server (`scripts/playground/server.py`, MLX on a Mac or
  PyTorch on CUDA), `POST /v1/systemone`. It applies its own rotations and calibration.
"""

import base64
import io
import json
import struct
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

import numpy as np
import requests
from PIL import Image

from .imajev import MAX_IMAGES, MEDIA, Engine, Question, render, to_jev_request

PATCH_MULTIPLE = 32  # Qwen3.5 vision: 16 px patches merged 2x2


class ScorerError(Exception):
    pass


class Scorer(Protocol):
    def describe(self) -> dict: ...

    def answer(self, questions: list[Question], state: object, photos: list[bytes]) -> dict: ...


def prepare_photo(data: bytes) -> bytes:
    """JPEG bytes both backends read identically: RGB, sides a multiple of 32 px (Street View photos already are)."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        w, h = (max(PATCH_MULTIPLE, round(s / PATCH_MULTIPLE) * PATCH_MULTIPLE) for s in img.size)
        if (w, h) == img.size:
            return data
        out = io.BytesIO()
        img.resize((w, h), Image.Resampling.BICUBIC).save(out, format="JPEG", quality=95)
        return out.getvalue()


def load_readout(path: Path) -> np.ndarray:
    """The readout matrix [codes, hidden] from a safetensors file holding one tensor `weight`."""
    raw = path.read_bytes()
    (n,) = struct.unpack("<Q", raw[:8])
    header = json.loads(raw[8:8 + n])
    entry = header["weight"]
    dtypes = {"F32": np.float32, "F16": np.float16, "BF16": None}
    if entry["dtype"] not in dtypes:
        raise ScorerError(f"unsupported readout dtype {entry['dtype']}")
    start, end = entry["data_offsets"]
    blob = raw[8 + n + start:8 + n + end]
    if entry["dtype"] == "BF16":
        u16 = np.frombuffer(blob, dtype=np.uint16).astype(np.uint32) << 16
        return u16.view(np.float32).reshape(entry["shape"])
    return np.frombuffer(blob, dtype=dtypes[entry["dtype"]]).astype(np.float32).reshape(entry["shape"])


class LlamaCppReadout:
    def __init__(self, base_url: str, readout: Path, engine: Engine, describe: dict, parallel: int = 4,
                 timeout_s: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.readout = load_readout(readout)
        self.engine = engine
        self._describe = describe
        self.parallel = parallel
        self.timeout_s = timeout_s
        self.session = requests.Session()
        self._marker: str | None = None

    def describe(self) -> dict:
        return {**self._describe, "backend": "llamacpp-readout", "rotations": self.engine.rotations,
                "calibration": self.engine.calibration.version if self.engine.calibration else None}

    def marker(self) -> str:
        if self._marker is None:
            props = self.session.get(f"{self.base_url}/props", timeout=30).json()
            self._marker = props.get("media_marker") or "<__media__>"
        return self._marker

    def hidden(self, text: str, photos: list[bytes]) -> np.ndarray:
        """The final hidden state at the answer position (after the model's last norm)."""
        prompt = render(text, len(photos), self.marker())
        content = {"prompt_string": prompt, "multimodal_data": [base64.b64encode(p).decode() for p in photos]} \
            if photos else prompt
        for attempt in range(3):
            try:
                r = self.session.post(f"{self.base_url}/embedding", json={"content": content, "embd_normalize": -1},
                                      timeout=self.timeout_s)
            except requests.RequestException as error:
                if attempt == 2:
                    raise ScorerError(f"scorer server unreachable: {error}") from error
                time.sleep(2 + 4 * attempt)
                continue
            if r.status_code == 200:
                data = r.json()
                vector = data[0]["embedding"] if isinstance(data, list) else data["embedding"]
                if vector and isinstance(vector[0], list):  # per-token output: the last token
                    vector = vector[-1]
                return np.asarray(vector, dtype=np.float32)
            if r.status_code < 500 or attempt == 2:
                raise ScorerError(f"scorer server: HTTP {r.status_code}: {r.text[:300]}")
            time.sleep(2 + 4 * attempt)
        raise ScorerError("unreachable")

    def answer(self, questions: list[Question], state: object, photos: list[bytes]) -> dict:
        if len(photos) > MAX_IMAGES:
            raise ScorerError(f"Imajev takes at most {MAX_IMAGES} photos")
        photos = [prepare_photo(p) for p in photos]
        prompts = self.engine.prompts(questions, state)
        with ThreadPoolExecutor(self.parallel) as pool:
            hidden = list(pool.map(lambda p: self.hidden(p.text, photos), prompts))
        if hidden and hidden[0].shape[0] != self.readout.shape[1]:
            raise ScorerError(f"hidden size {hidden[0].shape[0]} does not match the readout {self.readout.shape}")
        logits = [(self.readout[: p.n_choices] @ h).astype(float).tolist() for p, h in zip(prompts, hidden)]
        return self.engine.answers(questions, prompts, logits)


class SystemOne:
    def __init__(self, base_url: str, describe: dict, timeout_s: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._describe = describe
        self.timeout_s = timeout_s
        self.session = requests.Session()

    def describe(self) -> dict:
        return {**self._describe, "backend": "systemone"}

    def answer(self, questions: list[Question], state: object, photos: list[bytes]) -> dict:
        if len(photos) > MAX_IMAGES:
            raise ScorerError(f"Imajev takes at most {MAX_IMAGES} photos")
        photos = [prepare_photo(p) for p in photos]
        files = [("image", (f"photo{i}.jpg", p, "image/jpeg")) for i, p in enumerate(photos)]
        r = self.session.post(f"{self.base_url}/v1/systemone", files=files,
                              data={"request": json.dumps(to_jev_request(questions, state))}, timeout=self.timeout_s)
        if r.status_code != 200:
            raise ScorerError(f"systemone server: HTTP {r.status_code}: {r.text[:300]}")
        return r.json()["answers"]


class LlamaCppSystemOne:
    """A Jev decision model whose GGUF carries its decision head, answered by llama-server itself on
    `POST /v1/systemone` (llama.cpp build 11773 or later), e.g. H2O Lightning 4B. JSON request; photos as data URLs in
    the top-level `images` array; every string NFC-normalized, as the model's tokenizer expects (llama.cpp does not
    normalize). The probabilities are the model's own, calibrated: no rotations, no client-side readout."""

    MAX_IMAGES = 8  # llama-server's limit

    def __init__(self, base_url: str, describe: dict, timeout_s: float = 600.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._describe = describe
        self.timeout_s = timeout_s
        self.session = requests.Session()

    def describe(self) -> dict:
        return {**self._describe, "backend": "llamacpp-systemone"}

    def answer(self, questions: list[Question], state: object, photos: list[bytes]) -> dict:
        if len(photos) > self.MAX_IMAGES:
            raise ScorerError(f"llama-server takes at most {self.MAX_IMAGES} images")
        body = _nfc(to_jev_request(questions, state))
        body["images"] = ["data:image/jpeg;base64," + base64.b64encode(prepare_photo(p)).decode() for p in photos]
        try:
            r = self.session.post(f"{self.base_url}/v1/systemone", json=body, timeout=self.timeout_s)
        except requests.RequestException as error:
            raise ScorerError(f"decision server: {error}") from error
        if r.status_code != 200:
            raise ScorerError(f"decision server: HTTP {r.status_code}: {r.text[:300]}")
        answers = r.json()["answers"]
        missing = {q.name for q in questions} - set(answers)
        if missing:
            raise ScorerError(f"decision server did not answer {sorted(missing)}")
        return answers


def _nfc(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {_nfc(k): _nfc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_nfc(v) for v in value]
    return value


__all__ = ["LlamaCppReadout", "LlamaCppSystemOne", "MEDIA", "Scorer", "ScorerError", "SystemOne", "load_readout",
           "prepare_photo"]
