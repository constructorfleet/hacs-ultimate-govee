# Every known transport path is an explicit adapter

The integration models every known Govee transport as a named adapter: AWS IoT, local LAN over UDP, local MQTT, BLE GATT, and BLE broadcast. Only AWS IoT and local LAN are implemented today; the others report `unsupported` rather than being absent or silently routed through a lookalike path. Provisioning paths (SoftAP/HTTP and Matter commissioning) are separate from command transports.

## Consequences

- Adding a transport does not change callers: it implements the existing adapter interface and registers itself with the router.
- An unavailable path is visible in diagnostics and in tests, not inferred from a missing class.
- `ptReal`, `pt`, `ptUrl`, and `multiSync` remain command strategies, not transports.
- Fallback happens only when a transport reports `not sent`; an accepted publish is never retried on another path.
