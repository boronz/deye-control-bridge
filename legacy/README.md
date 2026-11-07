# Legacy pyscript prototype

Before this became a HACS integration, the controller ran as a
[pyscript](https://github.com/custom-components/pyscript) module. It works and is kept
here as a fallback / reference, but it is **superseded** by
`custom_components/deye_bridge`.

Differences:

| | pyscript prototype | HACS integration |
|---|---|---|
| Entities | You create `input_number` helpers | Native `number` / `switch` / `select` / `sensor` |
| Connection | Calls the `solarman` integration's services | Owns the Modbus connection (V5 or TCP) |
| Snapshot | `input_text` (255 chars) | `.storage`, full register blocks |
| Config | Edit a dict in the file | Config flow + options flow |
| Tests | Core only | Core + import smoke tests |

If you want to use the prototype instead, copy `deye_bridge.py` to
`/config/pyscript/`, `../custom_components/deye_bridge/core.py` to
`/config/pyscript/modules/deye_bridge_core.py`, and `helpers.yaml` into your packages.
Note that the prototype leaves the Modbus connection to the Solarman integration, so
it can coexist with it (slowly), while the integration needs exclusive access.
