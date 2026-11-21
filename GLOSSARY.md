# Ultimate Govee

The domain of a Home Assistant integration that controls Govee appliances through Govee's cloud, AWS IoT, and local LAN interfaces.

## Language

### Devices and models

**Account**:
The Govee login that owns devices, effects, and tap-to-runs. One config entry represents one account.
_Avoid_: user, tenant, integration instance.

**Device**:
A Govee appliance known to an account, identified by its device id and model.
_Avoid_: appliance, product, unit.

**SKU**:
The Govee model code, such as `H7126`, that selects a device's profile. It may also select a family dialect, but never by category or prefix alone.
_Avoid_: model number, product code.

**Profile**:
The capability record for a SKU: kind, features, ranges, speeds, and gang count.
_Avoid_: capabilities, spec, model config.

**Family dialect**:
The frame encoding and decoding observed to be shared by a set of SKUs. A dialect is assigned from evidence — app research, captures, or a verified handler — never inferred from kind, product category, or model prefix. Two devices of the same kind may use different dialects.
_Avoid_: codec, handler, driver, protocol family.

**Fleet**:
The reconciled set of devices on an account, including their metadata, availability, and last-seen state.
_Avoid_: device registry, device manager, device store.

### Protocol and transport

**State**:
The decoded snapshot of a device's reported attributes, such as power, brightness, temperature, and mode.
_Avoid_: status, properties, attributes.

**Command**:
A high-level action requested by an entity, such as setting brightness or a target temperature.
_Avoid_: request, action.

**Reading**:
A measured value reported by a device, such as temperature, humidity, or water level.
_Avoid_: property, attribute.

**Setting**:
A user preference stored by the device or cloud, such as a notification toggle or child lock. A setting is not a live condition.
_Avoid_: status, state.

**Status flag**:
A device condition reported by the device, such as water lack, ice full, or a door open. A status flag is not a setting.
_Avoid_: setting, error.

**Wire command**:
The per-transport encoding of a Command, carrying the payload and envelope metadata that transport needs. Each Transport owns its own Wire command; a Wire command never crosses the adapter seam.
_Avoid_: packet, payload, message.

**Transport**:
A path by which commands and status requests reach a device, with one adapter per path. Known command paths are AWS IoT, local LAN over UDP, local MQTT, and BLE GATT; BLE broadcast is receive-only. SoftAP/HTTP and Matter are provisioning paths, not command transports. The integration currently implements AWS IoT and local LAN; other adapters are explicit and may report unsupported.
_Avoid_: channel, link, connection, backend.

**Tap-to-run**:
An account-level Govee automation that the integration exposes as a button.
_Avoid_: scene, shortcut, HA automation.

### Home Assistant surface

**Entity plan**:
The set of Home Assistant entities a device supports, including each entity's platform and metadata.
_Avoid_: capability table, entity map, platform mapping.

**Effects library**:
The catalogue of named light effects available for a SKU.
_Avoid_: scene library, effects cache.

**Effect**:
A named light effect made of one or more frames.
_Avoid_: scene, mode.

### Configuration

**Govee options**:
The normalized integration options for one config entry, such as polling cadence and enabled transports.
_Avoid_: settings, preferences, config.
