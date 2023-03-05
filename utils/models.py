import orjson
import typing

from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional, Union


class ApiUuidRequest(BaseModel):
    version: str


class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: typing.Any) -> bytes:
        return orjson.dumps(
            content,
            option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
        )

class V2Response_LastPosition(BaseModel):
    lat: float
    lon: float
    nic: int
    rc: int
    seen_pos: float


class V2Response_AcItem(BaseModel):
    alert: Optional[int] = None
    alt_baro: Optional[Union[int, str]] = None
    alt_geom: Optional[int] = None
    baro_rate: Optional[int] = None
    category: Optional[str] = None
    emergency: Optional[str] = None
    flight: Optional[str] = None
    gs: Optional[float] = None
    gva: Optional[int] = None
    hex: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    messages: int
    mlat: List[str]
    nac_p: Optional[int] = None
    nac_v: Optional[int] = None
    nav_altitude_mcp: Optional[int] = None
    nav_heading: Optional[float] = None
    nav_qnh: Optional[float] = None
    nic: Optional[int] = None
    nic_baro: Optional[int] = None
    r: Optional[str] = None
    rc: Optional[int] = None
    rssi: float
    sda: Optional[int] = None
    seen: float
    seen_pos: Optional[float] = None
    sil: Optional[int] = None
    sil_type: Optional[str] = None
    spi: Optional[int] = None
    squawk: Optional[str] = None
    t: Optional[str] = None
    tisb: List[str]
    track: Optional[float] = None
    type: str
    version: Optional[int] = None
    geom_rate: Optional[int] = None
    dbFlags: Optional[int] = None
    nav_modes: Optional[List[str]] = None
    true_heading: Optional[float] = None
    ias: Optional[int] = None
    mach: Optional[float] = None
    mag_heading: Optional[float] = None
    oat: Optional[int] = None
    roll: Optional[float] = None
    tas: Optional[int] = None
    tat: Optional[int] = None
    track_rate: Optional[float] = None
    wd: Optional[int] = None
    ws: Optional[int] = None
    gpsOkBefore: Optional[float] = None
    gpsOkLat: Optional[float] = None
    gpsOkLon: Optional[float] = None
    lastPosition: Optional[V2Response_LastPosition] = None
    rr_lat: Optional[float] = None
    rr_lon: Optional[float] = None
    calc_track: Optional[int] = None
    nav_altitude_fms: Optional[int] = None


class V2Response_Model(BaseModel):
    ac: List[V2Response_AcItem]
    ctime: int
    msg: str
    now: int
    ptime: int
    total: int
