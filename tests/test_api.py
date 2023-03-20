import pytest

from aioresponses import aioresponses
from fastapi.testclient import TestClient

from adsb_api.app import app
from adsb_api.utils.models import V2Response_Model, V2Response_AcItem


mocked_happy_V2Response_Model = V2Response_Model(
    ac=[
        V2Response_AcItem(
            hex="f1337",
            messages=1,
            mlat=["x"],
            rssi=0.1,
            seen=0.1,
            tisb=["y"],
            type="A321",
        )
    ],
    ctime=1700000000,
    msg="No error",
    now=1700000000,
    ptime=1700000000,
    total=1,
)


@pytest.fixture
def mock_happy_reapi():
    """Mocks the ReAPI service which is external to this project."""
    with aioresponses() as mock:
        mock.get(
            "http://reapi-readsb:30152/re-api/?all&jv2",
            body=mocked_happy_V2Response_Model.json(),
        )

        mock.get(
            "http://reapi-readsb:30152/re-api/?all&filter_squawk=1200&jv2",
            body=mocked_happy_V2Response_Model.json(),
        )
        mock.get(
            "http://reapi-readsb:30152/re-api/?filter_squawk=1200",
            body=mocked_happy_V2Response_Model.json(),
        )

        mock.get(
            "http://reapi-readsb:30152/re-api/?find_type=A320&jv2",
            body=mocked_happy_V2Response_Model.json(),
        )
        mock.get(
            "http://reapi-readsb:30152/re-api/?find_type=A320",
            body=mocked_happy_V2Response_Model.json(),
        )

        mock.get(
            "http://reapi-readsb:30152/re-api/?find_reg=G-KELS&jv2",
            body=mocked_happy_V2Response_Model.json(),
        )
        mock.get(
            "http://reapi-readsb:30152/re-api/?find_reg=G-KELS",
            body=mocked_happy_V2Response_Model.json(),
        )

        mock.get(
            "http://reapi-readsb:30152/re-api/?find_hex=4CA87C&jv2'",
            body=mocked_happy_V2Response_Model.json(),
        )
        mock.get(
            "http://reapi-readsb:30152/re-api/?find_hex=4CA87C",
            body=mocked_happy_V2Response_Model.json(),
        )

        mock.get(
            "http://reapi-readsb:30152/re-api/?find_callsign=JBU1942&jv2",
            body=mocked_happy_V2Response_Model.json(),
        )
        mock.get(
            "http://reapi-readsb:30152/re-api/?find_callsign=JBU1942",
            body=mocked_happy_V2Response_Model.json(),
        )

        mock.get(
            "http://reapi-readsb:30152/re-api/?circle=10.0,50.0,250&jv2",
            body=mocked_happy_V2Response_Model.json(),
        )
        mock.get(
            "http://reapi-readsb:30152/re-api/?circle=10.0,50.0,250",
            body=mocked_happy_V2Response_Model.json(),
        )

        yield mock


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_v2_all(mock_happy_reapi, test_client):
    response = test_client.get("/v2/all")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_pia(mock_happy_reapi, test_client):
    response = test_client.get("/v2/pia")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_mil(mock_happy_reapi, test_client):
    response = test_client.get("/v2/mil")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_ladd(mock_happy_reapi, test_client):
    response = test_client.get("/v2/ladd")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_squawk(mock_happy_reapi, test_client):
    response = test_client.get("/v2/sqk/1200")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"

    response = test_client.get("/v2/squawk/1200")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_aircarft_type(mock_happy_reapi, test_client):
    response = test_client.get("/v2/type/A320")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_registration(mock_happy_reapi, test_client):
    response = test_client.get("/v2/reg/G-KELS")
    resp = response.json()

    assert resp["msg"] == "No error"

    response = test_client.get("/v2/registration/G-KELS")
    resp = response.json()

    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_icao(mock_happy_reapi, test_client):
    response = test_client.get("/v2/icao/4CA87C")
    resp = response.json()

    assert resp["msg"] == "No error"

    response = test_client.get("/v2/hex/4CA87C")
    resp = response.json()

    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_callsign(mock_happy_reapi, test_client):
    response = test_client.get("/v2/callsign/JBU1942")
    resp = response.json()

    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_radius(mock_happy_reapi, test_client):
    response = test_client.get("/v2/lat/10/lon/50/dist/500")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"

    response = test_client.get("/v2/point/10/50/500")
    resp = response.json()

    assert len(resp["ac"]) > 0, "No aircraft in response"
    assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_api_me(test_client):
    response = test_client.get("/api/0/me")
    resp = response.json()

    assert "clients" in resp.keys()
