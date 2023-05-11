from adsb_api.utils.provider import Provider
from adsb_api.utils.provider import RedisVRS
from adsb_api.utils.provider import FeederData
from adsb_api.utils.settings import ENABLED_BG_TASKS
from adsb_api.utils.browser2 import BrowserTabPool, before_add_to_pool_cb, before_return_to_pool_cb

provider = Provider(enabled_bg_tasks=ENABLED_BG_TASKS)
redisVRS = RedisVRS()
feederData = FeederData()
browser = BrowserTabPool(
    url="https://globe.adsb.lol/",
    before_add_to_pool_cb=before_add_to_pool_cb,
    before_return_to_pool_cb=before_return_to_pool_cb,
)
