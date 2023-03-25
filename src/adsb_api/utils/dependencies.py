from adsb_api.utils.provider import Provider
from adsb_api.utils.provider import RedisVRS
from adsb_api.utils.provider import FeederData
from adsb_api.utils.settings import ENABLED_BG_TASKS


provider = Provider(enabled_bg_tasks=ENABLED_BG_TASKS)
redisVRS = RedisVRS()
feederData = FeederData()
