import json
import typing

from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional, Union


class ApiUuidRequest(BaseModel):
    version: str


class PrettyJSONResponse(Response):
    media_type = "application/json"

    def render(self, content: typing.Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


class V2Response_LastPosition(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    nic: Optional[int] = None
    rc: Optional[int] = None
    seen_pos: Optional[float] = None


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
    hex: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    messages: Optional[int] = None
    mlat: Optional[List[str]] = None
    nac_p: Optional[int] = None
    nac_v: Optional[int] = None
    nav_altitude_mcp: Optional[int] = None
    nav_heading: Optional[float] = None
    nav_qnh: Optional[float] = None
    nic: Optional[int] = None
    nic_baro: Optional[int] = None
    r: Optional[str] = None
    rc: Optional[int] = None
    rssi: Optional[float] = None
    sda: Optional[int] = None
    seen: Optional[float] = None
    seen_pos: Optional[float] = None
    sil: Optional[int] = None
    sil_type: Optional[str] = None
    spi: Optional[int] = None
    squawk: Optional[str] = None
    t: Optional[str] = None
    tisb: Optional[List[str]] = None
    track: Optional[float] = None
    type: Optional[str] = None
    version: Optional[int] = None
    geom_rate: Optional[int] = None
    ias: Optional[int] = None
    mach: Optional[float] = None
    mag_heading: Optional[float] = None
    nav_modes: Optional[List[str]] = None
    oat: Optional[int] = None
    roll: Optional[float] = None
    tas: Optional[int] = None
    tat: Optional[int] = None
    track_rate: Optional[float] = None
    true_heading: Optional[float] = None
    wd: Optional[int] = None
    ws: Optional[int] = None
    dbFlags: Optional[int] = None
    nav_altitude_fms: Optional[int] = None
    gpsOkBefore: Optional[float] = None
    gpsOkLat: Optional[float] = None
    gpsOkLon: Optional[float] = None
    lastPosition: Optional[V2Response_LastPosition] = None
    rr_lat: Optional[float] = None
    rr_lon: Optional[float] = None
    calc_track: Optional[int] = None


class V2Response_Model(BaseModel):
    ac: Optional[List[V2Response_AcItem]] = None
    ctime: Optional[int] = None
    msg: Optional[str] = None
    now: int
    ptime: Optional[int] = None
    total: Optional[int] = None
