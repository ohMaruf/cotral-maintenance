"""Plain data types shared across modules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Stop:
    stop_id: str
    name: str
    lat: float
    lon: float
    location_type: str = "0"
    parent_station: str = ""


@dataclass(frozen=True)
class View:
    """One named image in a stop's shot plan, with its camera settings.
    The shot plan (panoramas.plan_shots) decides the panorama and heading.
    """

    name: str
    pitch: float = 0.0
    fov: float = 90.0
    size: str = "640x640"

    @property
    def key(self) -> str:
        """Stable identifier, used as the cache file name. Includes the size, so
        images at another resolution are never mistaken for cached ones."""
        return f"{self.name}_{self.size}"

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
