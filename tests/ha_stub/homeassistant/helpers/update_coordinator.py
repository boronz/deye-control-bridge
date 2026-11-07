from typing import Generic, TypeVar
T = TypeVar("T")
class UpdateFailed(Exception): pass
class Entity: pass
class CoordinatorEntity(Generic[T], Entity):
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = None
        self.entity_id = None
    @property
    def available(self): return True
    async def async_added_to_hass(self): pass
    def async_on_remove(self, fn): pass
    def async_write_ha_state(self): pass
class DataUpdateCoordinator(Generic[T]):
    def __init__(self, hass, logger, *, name=None, update_interval=None):
        self.hass = hass; self.logger = logger; self.name = name
        self.update_interval = update_interval; self.data = None
        self.last_update_success = True
    async def async_config_entry_first_refresh(self): self.data = None
    async def async_request_refresh(self): pass
