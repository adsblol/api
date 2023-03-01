import pytest
import aiohttp


@pytest.fixture
def test_client():
    return aiohttp.ClientSession(
        headers={"User-agent": "adsblol integration test"}, raise_for_status=True
    )


HOST = "https://api.adsb.lol"


@pytest.mark.asyncio
async def test_v2_all(test_client):
    async with test_client.get(f"{HOST}/v2/all") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_pia(test_client):
    async with test_client.get(f"{HOST}/v2/pia") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_mil(test_client):
    async with test_client.get(f"{HOST}/v2/mil") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_ladd(test_client):
    async with test_client.get(f"{HOST}/v2/ladd") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_squawk(test_client):
    async with test_client.get(f"{HOST}/v2/sqk/1200") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"

    async with test_client.get(f"{HOST}/v2/squawk/1200") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_aircarft_type(test_client):
    async with test_client.get(f"{HOST}/v2/type/A320") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_registration(test_client):
    async with test_client.get(f"{HOST}/v2/reg/G-KELS") as response:
        resp = await response.json()

        assert resp["msg"] == "No error"

    async with test_client.get(f"{HOST}/v2/registration/G-KELS") as response:
        resp = await response.json()

        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_icao(test_client):
    async with test_client.get(f"{HOST}/v2/icao/4CA87C") as response:
        resp = await response.json()

        assert resp["msg"] == "No error"

    async with test_client.get(f"{HOST}/v2/hex/4CA87C") as response:
        resp = await response.json()

        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_callsign(test_client):
    async with test_client.get(f"{HOST}/v2/callsign/JBU1942") as response:
        resp = await response.json()

        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_radius(test_client):
    async with test_client.get(f"{HOST}/v2/lat/10/lon/50/dist/500") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"

    async with test_client.get(f"{HOST}/v2/point/10/50/500") as response:
        resp = await response.json()

        assert len(resp["ac"]) > 0, "No aircraft in response"
        assert resp["msg"] == "No error"


@pytest.mark.asyncio
async def test_v2_radius(test_client):
    async with test_client.get(f"{HOST}/api/0/me") as response:
        resp = await response.json()

        assert "clients" in resp.keys()
