"""Plain data types shared across modules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Stop:
    stop_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class View:
    """How to photograph a stop: from the panorama closest to `distance_m` away,
    with the camera aimed at the stop. Several views per stop give several images.
    """

    distance_m: float = 0.0
    pitch: float = 0.0
    fov: float = 90.0
    size: str = "640x640"

    @property
    def key(self) -> str:
        """Stable identifier, used as the cache file name."""
        return f"d{self.distance_m:03.0f}_p{self.pitch:+03.0f}_f{self.fov:03.0f}_{self.size}"

    def to_params(self) -> dict[str, str]:
        return {"pitch": str(self.pitch), "fov": str(self.fov), "size": self.size}


@dataclass(frozen=True)
class PanoMetadata:
    pano_id: str
    lat: float
    lon: float
    date: str | None = None
    copyright: str = ""

    @property
    def is_google(self) -> bool:
        """False for user-uploaded photospheres, which are often indoors, at night or blurry."""
        return "Google" in self.copyright


@dataclass(frozen=True)
class Shot:
    """A panorama to photograph a stop from, and the camera heading that faces the stop."""

    pano: PanoMetadata
    distance_m: float
    heading: float
