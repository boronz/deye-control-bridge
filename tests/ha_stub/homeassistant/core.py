class HomeAssistant:
    async def async_add_executor_job(self, target, *args):
        return target(*args)
class Event: pass
class ServiceCall:
    data = {}
def callback(fn): return fn
