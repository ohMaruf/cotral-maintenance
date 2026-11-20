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
    name: str
    pitch: float = 0.0
    fov: float = 90.0
    size: str = "640x640"

    @property
    def key(self) -> str:
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
        return "Google" in self.copyright


@dataclass(frozen=True)
class Shot:
    pano: PanoMetadata
    distance_m: float
    heading: float
