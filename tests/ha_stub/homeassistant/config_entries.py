from typing import Any
class ConfigEntry:
    def __init__(self, entry_id="e1", data=None, options=None, title="Deye inverter"):
        self.entry_id = entry_id; self.data = data or {}; self.options = options or {}; self.title = title
        self.runtime_data = None
    def async_on_unload(self, fn): return fn
    def add_update_listener(self, fn): return fn
class ConfigFlow:
    VERSION = 1
    def __init_subclass__(cls, *, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
    def __init__(self): self.hass = None; self._unique_id = None
    async def async_set_unique_id(self, uid): self._unique_id = uid
    def _abort_if_unique_id_configured(self): pass
    def async_show_form(self, **k): return k
    def async_create_entry(self, **k): return k
class OptionsFlow:
    config_entry: ConfigEntry
