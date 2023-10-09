from adsb_api.utils.provider import RedisVRS
from adsb_api.utils.settings import ENABLED_BG_TASKS
from adsb_api.utils.browser2 import (
    BrowserTabPool,
    before_add_to_pool_cb,
    before_return_to_pool_cb,
)

redisVRS = RedisVRS()
browser = BrowserTabPool(
    url="https://adsb.lol/",
    before_add_to_pool_cb=before_add_to_pool_cb,
    before_return_to_pool_cb=before_return_to_pool_cb,
)
