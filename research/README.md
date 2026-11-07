# Source material

Downloads used while writing the docs. They are here so the claims can be checked
without hunting for the documents again.

| File | What it is | Source |
|---|---|---|
| `proto1.pdf`, `proto1.txt` | Deye *MODBUS RTU 三相储能通信规约* V105 (47 pp., Chinese) | [akkudoktor mirror](https://akkudoktor.net/uploads/short-url/ezKBX2l8uHmLk9qJyPxDfGLhYqP.pdf) |
| `proto2.pdf`, `proto2.txt` | Same protocol, V105.1 (53 pp.) | [akkudoktor mirror](https://akkudoktor.net/uploads/short-url/nbQbzSQaFFe3UdycjiVVVv5f7Y0.pdf) |
| `manual_sm2.pdf`, `manual_sm2.txt` | Deye SUN-4…12K-SG05LP3-EU-SM2 user manual (German) — System Work Mode and Time-of-Use chapters | [de.deyeinverter.com](https://de.deyeinverter.com/deyeinverter/2025/08/12/%E3%80%90b%E3%80%91%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6-%E5%82%A8%E8%83%BD%E4%B8%89%E7%9B%B8-sun-4-12k-sg05lp3-eu-sm2.pdf) |
| `solarman_deye_sg04lp3.yaml` | Solarman integration's register profile for this inverter family | [GitHub](https://github.com/StephanJoubert/home_assistant_solarman/blob/main/custom_components/solarman/inverter_definitions/deye_sg04lp3.yaml) |
| `solarman_services.py`, `solarman_services.yaml`, `solarman_lib.py`, `solarman_advanced.md`, `solarman_readme.md` | Solarman integration write services and docs | [GitHub](https://github.com/StephanJoubert/home_assistant_solarman) |
| `evcc_deye_hybrid_3p.yaml` | evcc battery-control template — reference for the charge/hold state machine | [GitHub](https://github.com/evcc-io/evcc/blob/master/templates/definition/meter/deye-hybrid-3p.yaml) |
| `sun_3ph_hybrid.yaml` | deye-modbus-ha's YAML map for this model | [GitHub](https://github.com/Developer089/deye-modbus-ha) |
| `protocol.py` | deye-controller's writable-register definitions (single-phase map, useful cross-check) | [GitHub](https://github.com/githubDante/deye-controller) |
