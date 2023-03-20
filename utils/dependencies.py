from utils.provider import Provider
from utils.provider import RedisVRS
from utils.settings import ENABLED_BG_TASKS
provider = Provider(enabled_bg_tasks=ENABLED_BG_TASKS)
redisVRS = RedisVRS()
