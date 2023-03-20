from unittest import mock

# Gotta do this in order for test to work when FastAPI cache is being used
mock.patch("fastapi_cache.decorator.cache", lambda *args, **kwargs: lambda f: f).start()
