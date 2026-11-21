# Govee appliances — reverse-engineered protocol reference

Humidifiers, purifiers, dehumidifiers and diffusers, extracted from the
`homebridge-govee` JavaScript plugin (read-only source). Everything below is
what that code actually sends and parses — no protocol guesswork beyond what is
explicitly marked as uncertain.

Source root (referred to as `SRC` below):
`/private/var/folders/sc/xq3g1qgx3hd0gl10w2l8rnm80000gn/T/opencode/homebridge-govee`

---

## 1. Transport and AWS IoT envelope

All appliance traffic is Govee's AWS IoT MQTT channel. Topics are per-account
(`accountTopic`) and per-device (`awsTopic`); the account topic is appended to
every outgoing message purely for routing (`SRC/lib/connection/aws.js:194-208`).

### 1.1 Outgoing command

`updateDevice()` wraps every command identically (`SRC/lib/connection/aws.js:163-185`):

```json
{
  "msg": {
    "cmd": "ptReal",
    "cmdVersion": 0,
    "data": { "command": ["MwUBAQAAAAAAAAAAAAAAAAAAADY="] },
    "transaction": "v_1732170000123007",
    "type": 1,
    "accountTopic": "<account topic>"
  }
}
```

| Field | Value | Reference |
| --- | --- | --- |
| `cmdVersion` | always `0` for commands | `aws.js:173` |
| `type` | `1` (command) | `aws.js:176` |
| `transaction` | `` `v_${Date.now()}${seq}` ``, `seq` cycles 0–999 | `aws.js:187-192` |
| `data.command` | **array of base64 strings**, one base64 packet per frame | `SRC/lib/utils/command-builder.js:142-162` |

### 1.2 Status request (polling)

Humidifier / dehumidifier / purifier / diffuser families all set
`awsPolling: true` (`SRC/lib/utils/dispatch.js:76-99`), so the platform asks for
status on a timer (`SRC/lib/platform.js:1337-1340`, 60 s):

```json
{
  "msg": {
    "cmd": "status",
    "cmdVersion": 2,
    "transaction": "v_1732170000123007",
    "type": 0,
    "accountTopic": "<account topic>"
  }
}
```

`cmdVersion` is **2** by default; only `H6121` overrides it to `1`
(`SRC/lib/connection/aws.js:139`, `SRC/lib/utils/device-capabilities.js:161-162`, `:263`).

### 1.3 Incoming report

The device publishes the same envelope with `op.command` (array of base64
frames) and/or `state.*`. The plugin normalises:

| Incoming shape | Normalised to | Reference |
| --- | --- | --- |
| `op.command` (array) | `commands`, `baseCmd = 'op'` | `SRC/lib/utils/response-parser.js:266-272` |
| `op.mode` + `op.value` array | `commands`, `baseCmd = 'opMode'` | `:273-275` |
| `op.opcode === 'mode'` + `op.modeValue` array | `commands`, `baseCmd = 'opCodeMode'` | `:276-278` |
| `bulb` | `commands`, `baseCmd = 'bulb'` | `:280-282` |
| `data.op === 'mode'` + `data.value` array | `commands`, `baseCmd = 'opMode'` | `:283-285` |
| `state.onOff` | `state: 'on'` for `1` **and** `17`, else `'off'` | `:110-133` |
| `state.workMode` | `workMode` (`{workMode, modeValue}`) | `:226-229` |
| `state.toggles.*` | `toggles` (`nightlightToggle`, `lockToggle`, `displayToggle`, …) | `:231-234` |
| `state.filterLife` | `filterLife` (number) | `:178-181` |
| `state.waterShortage` | `waterShortage` | `:183-186` |
| `state.humidity` | `humidity` | `:221-224` |
| `state.targetHumidity` | `targetHumidity` | `:241-244` |
| `state.sensorHumidity` | `humidity = value * 100` | `:260-263` |

OpenAPI (REST/MQTT) capability → normalised field
(`SRC/lib/connection/openapi.js:140-190`, `:480-525`):

| OpenAPI instance | Normalised | Notes |
| --- | --- | --- |
| `powerSwitch` | `onOff` | number |
| `workMode` | `workMode` | `{workMode, modeValue}` |
| `sensorHumidity` | `sensorHumidity` | raw, ×100 later |
| `filterLifeTime` | `filterLife` | percent |
| `lackWaterEvent` | `waterShortage` | **only ever sent as 1** (dry); no refill event |
| `humidity` | `targetHumidity` | this is the *target* humidity capability |
| `*Toggle` | `toggles[instance]` | e.g. `nightlightToggle` |

---

## 2. Packet framing (every `ptReal` frame)

`generateCodeFromHexValues()` (`SRC/lib/utils/functions.js:22-44`):

1. Payload bytes are concatenated (max **19** bytes — throws above that).
2. Zero-padded to 19 bytes.
3. Byte 20 = XOR of the first 19 bytes.
4. The 20-byte buffer is base64-encoded and put in `data.command[]`.

```
byte  0        1      2..n                      19
      opcode   sub    payload                   XOR checksum
```

Byte positions used in this document are **1-based** (`byte1` = opcode), matching
`getTwoItemPosition(arr, n) => arr[n-1]` (`SRC/lib/utils/functions.js:55`).
`hexToTwoItems()` splits the hex string into 2-char byte strings.

Common opcodes for these families:

| Opcode | Meaning | Direction |
| --- | --- | --- |
| `0x33` | command (set) | out |
| `0x3A` (58) | command (set), purifier H7122/H7123 only | out |
| `0xAA` | status report / query update | in |
| `0x33` echo | acknowledgement of a `0x33` command | in (ignored) |

---

## 3. Model → handler map

(`SRC/lib/utils/constants.js:774-800`, `SRC/lib/device/index.js:52-113`)

| Family | Models | Handler |
| --- | --- | --- |
| humidifier | H7140 | `humidifier-H7140.js` |
| humidifier | H7141 | `humidifier-H7141.js` |
| humidifier | H7142 | `humidifier-H7142.js` |
| humidifier | H7143, H7145, H7147, H7148, H7149, H714E | `humidifier-H7143.js` (aliases) |
| humidifier | H7146 | *no handler alias* → falls back to `deviceHumidifierBasic` |
| humidifier | H7160 | `humidifier-H7160.js` |
| purifier | H7120, H7121 | `purifier-H7120.js` |
| purifier | H7122 | `purifier-H7122.js` |
| purifier | H7123, H7124 | `purifier-H7123.js` |
| purifier | H7126, H7127, H7128, H7129, H712C | `purifier-H7126.js` |
| purifier | any socket configured `showAs: 'purifier'` | `purifier-single.js` (`dispatch.js:135-136`) |
| dehumidifier | H7150, H7151, H7152 | `dehumidifier-H7150.js` |
| diffuser | H7161, H7162 | `diffuser-H7161.js` |
| fallback | any unlisted model in the family | `appliance-basic.js` (`dispatch.js:76-99`) |

Note: `H7146` is listed in the humidifier SKU list but has no `deviceHumidifierH7146`
alias in `device/index.js`, so it gets the generic handler (power + a slider that
reports "not implemented"). Worth checking before relying on it.

---

## 4. Entity capabilities and HA platform mapping

HomeKit services are listed because they are what the plugin builds; the HA
column is the natural equivalent.

### 4.1 Humidifiers

| Model | HomeKit service | Characteristics | HA platform |
| --- | --- | --- | --- |
| H7140 | `Fan` | `On`, `RotationSpeed` 0–8 (unitless, step 1) | `fan` (speed 1–8) |
| H7140 | `Lightbulb` | `On` only | `light` (on/off) |
| H7140 | `ContactSensor` "Water Tank" | `ContactSensorState` | `binary_sensor` (moisture) |
| H7141 | `Fan` | `On`, `RotationSpeed` 0–8 | `fan` (speed 1–8) |
| H7141 | `ContactSensor` "Water Tank" | `ContactSensorState` | `binary_sensor` |
| H7142 | `Fan` | `On`, `RotationSpeed` 0–9 | `fan` (speed 1–9) |
| H7142 | `HumiditySensor` | `CurrentRelativeHumidity` (0–100 %) | `sensor` (humidity) |
| H7142 | `Lightbulb` | `On`, `Brightness`, `Hue`, `Saturation` | `light` (RGB + brightness) |
| H7142 | `ContactSensor` "Water Tank" | `ContactSensorState` | `binary_sensor` |
| H7143 (+ aliases) | `Fan` | `On`, `RotationSpeed` 0–8 | `fan` (speed 1–8) |
| H7143 (+ aliases) | `ContactSensor` "Water Tank" | `ContactSensorState` | `binary_sensor` |
| H7160 | `Fan` | `On`, `RotationSpeed` 0–9 | `fan` (speed 1–9) |
| H7160 | `Lightbulb` | `On`, `Brightness`, `Hue`, `Saturation` | `light` |
| H7160 | `ContactSensor` "Water Tank" | `ContactSensorState` | `binary_sensor` |
| generic | `Fan` (or `HumidifierDehumidifier` if it reports humidity) | `On`/`Active`, `RotationSpeed` (non-functional) | `fan` / `humidifier` |

References: H7140 `SRC/lib/device/humidifier-H7140.js:36-69`; H7141 `:68-90`;
H7142 `:79-139`; H7143 `:34-55`; H7160 `:40-102` (and `:43-46`, which **removes**
any existing `HumiditySensor` — the H7160 deliberately has no humidity tile).

**No humidifier handler exposes a target-humidity control, and none sends a
set-target frame.** The only target-humidity data path in the whole plugin is
read-only: OpenAPI instance `humidity` → `params.targetHumidity`
(`SRC/lib/connection/openapi.js:185-186`, `SRC/lib/utils/response-parser.js:241-244`),
and no handler reads `targetHumidity`. The generic handler does offer
`RelativeHumidityHumidifierThreshold`, but its setter always fails on purpose
(`SRC/lib/device/appliance-basic.js:231-248`).

### 4.2 Purifiers

| Model | HomeKit service | Characteristics | HA platform |
| --- | --- | --- | --- |
| H7120 | `AirPurifier` | `Active`, `CurrentAirPurifierState`, `TargetAirPurifierState` (forced 1 = Auto) | `fan` |
| H7120 | `AirPurifier` | `RotationSpeed` 0/25/50/75/100 (step 25) | `fan` speed / preset |
| H7120 | `AirPurifier` | `LockPhysicalControls` | `switch` (child lock) |
| H7120 | `AirPurifier` | custom `NightLight`, custom `DisplayLight` | `switch` ×2 |
| H7120 | `FilterMaintenance` | `FilterLifeLevel`, `FilterChangeIndication` | `sensor` + `binary_sensor` |
| H7122 | `AirPurifier` | as H7120 but `RotationSpeed` 0/20/40/60/80/100 | `fan` + `select` (mode) |
| H7122 | `AirQualitySensor` | `PM2_5Density` + `AirQuality` | `sensor` (pm25) |
| H7122 | `AirPurifier` | `LockPhysicalControls`, `NightLight`, `DisplayLight` | `switch` ×3 |
| H7123 | `AirPurifier` | as H7122, 20 % steps | `fan` + `select` |
| H7123 | `AirQualitySensor` | `AirQuality` only (PM2.5 characteristic removed) | `sensor` (enum) |
| H7123 | `AirPurifier` | `LockPhysicalControls`, `NightLight`, `DisplayLight` | `switch` ×3 |
| H7126 | `AirPurifier` | `TargetAirPurifierState` forced **0 = Manual** | `fan` |
| H7126 | `AirPurifier` | `RotationSpeed` 0/33/66/99 (step 33) | `fan` speed (3 levels) |
| H7126 | `AirPurifier` | `LockPhysicalControls`, `DisplayLight` (**no night light**) | `switch` ×2 |
| any (showAs purifier) | `AirPurifier` | `Active`, `CurrentAirPurifierState` only | `fan` (on/off) |

References: H7120 `:55-119`; H7122 `:77-150`; H7123 `:80-154`; H7126 `:52-101`;
`purifier-single.js:22-41`.

### 4.3 Dehumidifier and diffuser

| Model | HomeKit service | Characteristics | HA platform |
| --- | --- | --- | --- |
| H7150/51/52 | `Fan` | `On`, `RotationSpeed` 0–8 | `fan` (speed 1–8) |
| H7161/62 | `AirPurifier` | `Active`, `CurrentAirPurifierState` | `fan` (on/off only) |

H7150 builds no humidity, tank or mode tile (`dehumidifier-H7150.js:58-79`);
H7161 explicitly removes a stale `Fan` service and keeps its pre-existing Eve
history (`diffuser-H7161.js:13-20`, `:43-46`).

### 4.4 Shared tiles (gated on OpenAPI capability discovery)

| Tile | Gate | Behaviour | Reference |
| --- | --- | --- | --- |
| `FilterMaintenance` | `openApiCapabilities.filterLifeTime` | `FilterLifeLevel` 0–100; `FilterChangeIndication = 1` at ≤ 10 % | `SRC/lib/device/base.js:85-114` |
| `ContactSensor` "Water Tank" | `openApiCapabilities.lackWaterEvent` | closed = water present; opens on `waterShortage`; **only re-closes when the device goes off→on** (assumed refill) | `base.js:116-156` |

---

## 5. Command frames

### 5.1 Power — this is *not* a `0x33 0x01` frame for these models

Every named humidifier/purifier/dehumidifier/diffuser handler sends power as
`cmd: 'stateHumi'` (humidifiers, dehumidifier, diffuser) or `'statePuri'`
(purifiers). Those build an AWS **`turn`** command, not `ptReal`
(`SRC/lib/utils/command-builder.js:18-20`, `:111-123`):

```json
{ "msg": { "cmd": "turn", "cmdVersion": 0, "data": { "val": 1 }, "type": 1, ... } }
```

`val` is `1` for on, `0` for off. There is **no base64 frame and no checksum**
for power on these models. In parallel the plugin writes the OpenAPI
`powerSwitch` / `devices.capabilities.on_off` capability.

`purifier-single.js` uses `cmd: 'stateOutlet'` instead
(`purifier-single.js:76-79`), which is also `turn`, but `val` comes from the
capability table (`caps.awsPowerOn` / `awsPowerOff`, default 1/0) —
`command-builder.js:96-109`.

Only the **generic** handler sends a real power frame
(`appliance-basic.js:199-211`):

| State | Hex (20 B) | Base64 |
| --- | --- | --- |
| on | `33 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 33` | `MwEBAAAAAAAAAAAAAAAAAAAAADM=` |
| off | `33 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 32` | `MwEAAAAAAAAAAAAAAAAAAAAAADI=` |

These two are described in code as "the same for every govee appliance"
(`appliance-basic.js:199-200`).

### 5.2 Humidifier / dehumidifier speed ("gear") frames — `33 05 01 <level>`

Used by H7140 (levels 1–8), H7141 (1–8), H7142 (**1–9**), H7143 + aliases (1–8),
H7160 (**1–9**), H7150 (1–8). Sent via `cmd: 'ptReal'`.

Layout: `33 05 01 <level>` + 15 × `00` + XOR checksum (`0x37 ^ level`).
References: `humidifier-H7140.js:16-25`, `H7141.js:48-57`, `H7142.js:54-64`,
`H7143.js:14-23`, `H7160.js:19-29`, `dehumidifier-H7150.js:39-48`.

| Level | Hex (20 B) | Base64 |
| --- | --- | --- |
| 1 | `33 05 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 36` | `MwUBAQAAAAAAAAAAAAAAAAAAADY=` |
| 2 | `33 05 01 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 35` | `MwUBAgAAAAAAAAAAAAAAAAAAADU=` |
| 3 | `33 05 01 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 34` | `MwUBAwAAAAAAAAAAAAAAAAAAADQ=` |
| 4 | `33 05 01 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 33` | `MwUBBAAAAAAAAAAAAAAAAAAAADM=` |
| 5 | `33 05 01 05 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 32` | `MwUBBQAAAAAAAAAAAAAAAAAAADI=` |
| 6 | `33 05 01 06 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 31` | `MwUBBgAAAAAAAAAAAAAAAAAAADE=` |
| 7 | `33 05 01 07 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 30` | `MwUBBwAAAAAAAAAAAAAAAAAAADA=` |
| 8 | `33 05 01 08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3F` | `MwUBCAAAAAAAAAAAAAAAAAAAAD8=` |
| 9 | `33 05 01 09 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 3E` | `MwUBCQAAAAAAAAAAAAAAAAAAAD4=` |

Every one of these is sent with an optional OpenAPI `workMode` write
(`devices.capabilities.work_mode`):

```json
{ "instance": "workMode", "capabilityType": "devices.capabilities.work_mode",
  "value": { "workMode": 1, "modeValue": <level> } }
```

(`humidifier-H7140.js:117-127`, `H7141.js:138-148`, `H7142.js:210-220`,
`H7143.js:103-113`, `H7160.js:158-168`, `dehumidifier-H7150.js:127-137`).
`workMode: 1` = the manual/gear work mode; `modeValue` = the gear.

### 5.3 Humidifier night light — `33 1B`

| Action | Hex | Base64 |
| --- | --- | --- |
| off | `33 1B 00` + 16 × `00` + `28` | `MxsAAAAAAAAAAAAAAAAAAAAAACg=` |
| on | `33 1B 01 <brightness 0–100> <R> <G> <B>` + zero pad + XOR | built at runtime |

Off frame built as `[0x33, 0x1B, 0x00]`; on frame as
`[0x33, 0x1B, 0x01, cacheBright, ...hs2rgb(hue, sat)]`
(`humidifier-H7140.js:149-170`, `H7142.js:241-271`, `H7160.js:189-219`).
The 7-byte on payload is inside the 19-byte budget, so checksum is
`33^1B^01^bright^R^G^B`.

`H7140` only has `On` (brightness comes from the cached characteristic but there
is no brightness setter — `H7140.js:64-69`, `:139-190`). **Its `cacheBright` is
never initialised** (`H7140.js:16-74` has no brightness handling), so the
night-light-on frame's brightness byte serialises as `0x00`; an integration
should substitute a real level (the other handlers use 0–100, `0x64` = 100 %).
`H7142` and `H7160` add a
350 ms debounced brightness setter (`[0x33,0x1B,0x01,value,R,G,B]`) and a 300 ms
debounced colour setter (`H7142.js:285-388`, `H7160.js:233-336`). Brightness `0`
is treated as off (`H7142.js:313-324`).

Optionally accompanied by `nightlightToggle` (`devices.capabilities.toggle`,
value 1/0) — H7140 `:171-178`, H7142 `:264-271`, H7160 `:212-219`.

### 5.4 H7142 UVC

Sent automatically 200 ms after power-on when the cached UV state is `off`
(`humidifier-H7142.js:161-170`):

| Action | Hex | Base64 |
| --- | --- | --- |
| UV on | `33 1A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 28` | `MxoBAAAAAAAAAAAAAAAAAAAAACg=` |

There is no user-facing UV control and no UV-off frame.

### 5.5 Purifier H7120 / H7121 — `33 05 <gear>`

Codes (`purifier-H7120.js:29-34`). Note the **sleep gear is `0x10` (16), not a
sequential level**, and the value sits in byte 3 (not byte 4 like the humidifiers).

| UI step | `speed2Value` | Frame (byte 3) | Hex | Base64 |
| --- | --- | --- | --- | --- |
| 25 % | 1 (sleep) | `10` | `33 05 10` + 16 × `00` + `26` | `MwUQAAAAAAAAAAAAAAAAAAAAACY=` |
| 50 % | 2 (low) | `01` | `33 05 01` + 16 × `00` + `37` | `MwUBAAAAAAAAAAAAAAAAAAAAADc=` |
| 75 % | 3 (medium) | `02` | `33 05 02` + 16 × `00` + `34` | `MwUCAAAAAAAAAAAAAAAAAAAAADQ=` |
| 100 % | 4 (high) | `03` | `33 05 03` + 16 × `00` + `35` | `MwUDAAAAAAAAAAAAAAAAAAAAADU=` |

`speed2Value = min(max(floor(percent / 25), 1), 4)` (`:26`). A reported `modeValue`
of 1–4 is multiplied by 25 for the slider (`:326-336`).

Other frames (`purifier-H7120.js:37-52`), all `ptReal`:

| Control | Hex | Base64 |
| --- | --- | --- |
| Night light on | `33 18 01 32` + 15 × `00` + `18` | `MxgBMgAAAAAAAAAAAAAAAAAAABg=` |
| Night light off | `33 18 00 32` + 15 × `00` + `19` | `MxgAMgAAAAAAAAAAAAAAAAAAABk=` |
| Child lock on | `33 10 01` + 16 × `00` + `22` | `MxABAAAAAAAAAAAAAAAAAAAAACI=` |
| Child lock off | `33 10 00` + 16 × `00` + `23` | `MxAAAAAAAAAAAAAAAAAAAAAAACM=` |
| Display on | `33 16 01` + 16 × `00` + `24` | `MxYBAAAAAAAAAAAAAAAAAAAAACQ=` |
| Display off | `33 16 00` + 16 × `00` + `25` | `MxYAAAAAAAAAAAAAAAAAAAAAACU=` |

The night-light frame always carries `32 00` (0x32 = 50) as its brightness byte;
no brightness control is exposed. Optional OpenAPI writes: `nightlightToggle`
(`:211-223`), `lockToggle` (`:247-258`), `displayToggle` (`:286-298`).

### 5.6 Purifier H7122 / H7123 / H7124 — prefix `0x3A`

These two models send `3A 05 …` instead of `33 05 …` (`purifier-H7122.js:54-60`,
`purifier-H7123.js:49-55`). Five modes are packed into byte 3–4:

| Mode | Byte 3–4 | Hex | Base64 |
| --- | --- | --- | --- |
| Sleep (1) | `05 00` | `3A 05 05 00` + 15 × `00` + `3A` | `OgUFAAAAAAAAAAAAAAAAAAAAADo=` |
| Low (2) | `01 01` | `3A 05 01 01` + 15 × `00` + `3F` | `OgUBAQAAAAAAAAAAAAAAAAAAAD8=` |
| Medium (3) | `01 02` | `3A 05 01 02` + 15 × `00` + `3C` | `OgUBAgAAAAAAAAAAAAAAAAAAADw=` |
| High (4) | `01 03` | `3A 05 01 03` + 15 × `00` + `3D` | `OgUBAwAAAAAAAAAAAAAAAAAAAD0=` |
| Auto (5) | `03 00` | `3A 05 03 00` + 15 × `00` + `3C` | `OgUDAAAAAAAAAAAAAAAAAAAAADw=` |

(The checksum is the XOR of the first 19 bytes, so sleep and auto coincidentally
both end in `…3A`/`…3C` patterns shown above.)

The slider maps `percent / 20` → 1..5 (20 % steps, `H7122.js:109-117`, `:199`).
Custom mode (6) exists in the API enum but is *not* sendable: it has no code,
and a report of `0202` is only logged as `custom` (`H7122.js:412-416`).

Night light / lock / display are byte-identical to the H7120 set:

* night light: `MxgBMg…` / `MxgAMg…` (`H7122.js:71-74`, `H7123.js:66-69`)
* lock: `MxAB…` / `MxAAAA…` (`H7122.js:277`, `H7123.js:281`)
* display: `MxYB…` / `MxYAAAA…` (`H7122.js:314-319`, `H7123.js:318-323`)

**Display-on is a replay, not a fixed frame.** If the device has reported
`aa 16 01 …`, the plugin stores that hex, rewrites the opcode from `aa` to `33`,
strips the old checksum and re-computes a new one (`statusToActionCode`,
`SRC/lib/utils/functions.js:125-131`). This preserves whatever display settings
the device reported. Fallback when nothing was cached is `MxYB…`.

### 5.7 Purifier H7126 family — `33 05 01 <level>` (3 levels)

`purifier-H7126.js:26-37`, `:16-24`:

| UI | Level | Hex | Base64 | Code comment |
| --- | --- | --- | --- | --- |
| 33 % | 1 | `33 05 01 01` + 15 × `00` + `36` | `MwUBAQAAAAAAAAAAAAAAAAAAADY=` | sleep |
| 66 % | 2 | `33 05 01 02` + 15 × `00` + `35` | `MwUBAgAAAAAAAAAAAAAAAAAAADU=` | low |
| 99 % | 3 | `33 05 01 03` + 15 × `00` + `34` | `MwUBAwAAAAAAAAAAAAAAAAAAADQ=` | high |

`speed2Value`: ≤ 33 → 1, ≤ 66 → 2, else 3; `value2Speed`: 33/66/99
(`:16-30`). Slider `validValues [0, 33, 66, 99]`.

Lock and display reuse the same constants as H7120 (`:40-49`): `MxAB…`/`MxAAAA…`,
`MxYB…`/`MxYAAAA…`. Lock write is optional `lockToggle`, display optional
`displayToggle`, speed optional `workMode` (`:162-172`, `:196-209`, `:236-248`).

### 5.8 Generic appliance (`appliance-basic.js`)

| Control | Frame | Reference |
| --- | --- | --- |
| power | `33 01 01` / `33 01 00` (see §5.1) | `appliance-basic.js:201-211` |
| swing | no bytes — OpenAPI `oscillationToggle` only, value 1/0 | `:117`, `:139-188` |
| lock | no bytes — OpenAPI `lockToggle` only | `:118`, `:139-188` |
| speed / ice size | **never sent** — reports and throws `-70402` | `:231-248` |

The two OpenAPI toggles are only offered when the device itself reported the
capability (`:146-153`); the command is `cmd: 'openApi'`, which builds **only**
`openApiParams` (`command-builder.js:164-171`).

---

## 6. Report frames and decoding

Frames arrive base64 in `op.command[]`. Every handler first checks
`byte1 === 'aa'` and then derives a 4-hex-digit `deviceFunction` from
`byte2 + byte3`, *except* H7122/H7123 (which use `byte1 + byte2`, i.e. `aa05`)
and the diffuser (which uses `byte1 + byte2` and therefore never matches).

### 6.1 Universal / cross-family

| Frame | Decode | Used by |
| --- | --- | --- |
| `AA 01 01` | power on | `appliance-basic.js:291-303` |
| `AA 01 00` | power off | `appliance-basic.js:291-303` |
| `AA 05 00 <mode>` | mode: `01` manual, `02` custom, `03` auto (others ignored) | H7141 `:194-223`, H7142 `:458-486`, H7160 `:382-410` |
| `AA 05 01 <level>` | gear/speed, decimal of byte 4 | H7141 `:224-235`, H7142 `:487-497`, H7160 `:411-421`, H7143 `:159-172`, H7150 `:184-195`, H7120 `:373-386`, H7126 `:323-339` |
| `AA 05 02 <level>` | gear/speed (secondary) | H7143 `:158-172`, H7150 `:184-195`, H7120 `:373-386` |
| `AA 05 03 …` | auto mode — ignored | H7142 `:562-569`, H7160 `:474-481` |
| `AA 05 <a> <b>` | mode pair, see §6.4 | H7122 `:408-454`, H7123 `:412-457` |
| `3A 05 <a> <b>` | same as above, 0x3A-prefixed report | H7122 `:409`, H7123 `:413` |
| `AA 10 00` / `AA 10 01` | lock off / on (deviceFunction `1000`/`1001`) | H7120 `:387-401`, H7126 `:340-353` |
| `AA 10 <0/1>` | lock off / on (byte 3 is the state) | H7122 `:455-467`, H7123 `:459-471` |
| `AA 16 00` / `AA 16 01` | display off / on | H7122 `:468-483`, H7123 `:472-487` |
| `AA 16 00`/`AA 16 01` (as `1600`/`1601`) | display off / on | H7126 `:354-370` |
| `AA 18 00`/`AA 18 01` | display off / on (logged only) | H7142 `:498-508`, H7160 `:422-432`, H7141 `:240-242` |
| `AA 18 00`/`AA 18 01` | "indicator light", ignored | H7141 `:240-242` |
| `AA 1A 00`/`AA 1A 01` | UVC off / on (logged only) | H7142 `:509-520` |
| `AA 1B 00`/`AA 1B 01` | night light off / on | H7140 `:236-247`, H7142 `:521-561`, H7160 `:433-473` |
| `AA 11 00`/`AA 11 01` | timer — ignored | H7141 `:236-239`, H7142 `:564-566`, H7160 `:476-478` |
| `AA 13 00`, `AA 15 00` | scheduling — ignored | H7141 `:238-239`, H7142 `:566-568` |
| `AA 10 <flags> <3-byte reading>` | humidity, see §6.2 | H7142 only |
| `AA 19 …` | air quality, see §6.5 | H7123 only |
| `AA 1C …` | PM2.5, see §6.6 | H7122 only |
| `33 10 …`, `33 11 …`, `33 13 …`, `33 16 …` | acknowledgements of lock/timer/schedule/display — ignored | H7122 `:547-551`, H7123 `:510-514` |

`AA 1B` night-light frames on H7142/H7160 also carry brightness and colour:
`brightness = byte4` (0–100), `RGB = byte5, byte6, byte7` (`H7142.js:532-559`,
`H7160.js:444-471`). Byte 3 is the state (`01` = on).

### 6.2 H7142 humidity: `AA 10 <flags> <3-byte reading>`

`humidifier-H7142.js:431-447`

| Field | Position | Meaning |
| --- | --- | --- |
| flags | byte 3 | bit 7 (`0x80`) = reading from the humidifier's own sensor; bit 0 (`0x01`) = from a linked thermometer. Test: `flags & 0x81` must be truthy |
| reading | bytes 4–6 | 24-bit big-endian |
| none | — | `0xFFFFFF` means "no reading" — the last value is kept |

Decoding (`:437-439`):

```
reading = int(byte4 byte5 byte6)
humidity_pct = round(((reading & 0x7FFFFF) % 1000) / 10)
```

The upper part of the word is a temperature, in tenths of °C × 1000:

```
temp_C = floor(reading / 1000) / 10        (the plugin does not use it)
```

Worked examples from the code and its test cases
(`SRC/lib/device/humidifier-H7142.test.js:31-56`):

| Frame | reading | Result |
| --- | --- | --- |
| `AA 10 81 00 02 12 …` | 530 | 53.0 % — own sensor, 0.0 °C |
| `AA 10 01 03 70 FA …` | 225530 | 53.0 % — 22.5 °C and 53.0 % from a linked thermometer |
| `AA 10 81 FF FF FF …` | 0xFFFFFF | ignored, previous value kept |

Range is 0–100 %. The plugin rounds to a whole percent for
`CurrentRelativeHumidity`; the raw resolution is 0.1 %.

H7142 also silently ignores these subtrees, to avoid log spam
(`:449-453`): `AA 08` (linked thermometer), `AA 12` (timers), `AA 17`
(cleaning reminders), `AA 1E` (humidity calibration), `AA 30` (charts).

H7160 has **no** humidity decode at all, and removes the sensor tile.

### 6.3 H7141 capture log (annotated in the source, `:256-270`)

These are real captured frames and are the best reference for the `AA 05`
family layout:

| Hex | Meaning per comment |
| --- | --- |
| `AA 05 00 01` | mode = manual |
| `AA 05 01 08` | manual speed = 8 |
| `AA 05 02 00 08 00 3C 00 3C 05 00 3C 00 3C 01 FF FF FF FF` | custom mode payload |
| `AA 05 03 B8` | auto mode, byte 4 = `B8` (184) |
| `AA 16 00 08 00 16 0F` | display/timer frame |
| `AA 08 6B 0B 35 37 32 C5` | linked thermometer (0x0B6B etc.) |
| `AA 10 01 02 FB DE` | humidity frame, flags `01`, reading `0x02FBDE` = 195550 → 55.0 % |
| `AA 18 00 08 00 16 0F` | display |
| `AA 1E 02 00` | humidity calibration |

These show that for the H7141, `AA 10` is the same humidity layout the H7142
decodes, even though the H7141 handler does not parse it.

### 6.4 H7122 / H7123 mode-pair reports: `AA 05 <a> <b>` / `3A 05 <a> <b>`

The plugin takes bytes 3–4 as a pair (`purifier-H7122.js:408-446`):

| Pair | Mode | Slider |
| --- | --- | --- |
| `05 00` | sleep | 1 → 20 % |
| `01 01` | low | 2 → 40 % |
| `01 02` | medium | 3 → 60 % |
| `01 03` | high | 4 → 80 % |
| `03 00` | auto | 5 → 100 % |
| `02 02` | custom | not represented — logged only, then `return` |

### 6.5 H7123 air quality: `AA 19 …`

`purifier-H7123.js:488-507`, byte 5 is the reading.

```
raw = int(byte5);  raw < 1 or NaN → 0 (unknown);  raw >= 4 → 5 (poor);  else keep
```

| Raw | HomeKit `AirQuality` | Label |
| --- | --- | --- |
| 0 / invalid | 0 | unknown |
| 1 | 1 | excellent |
| 2 | 2 | good |
| 3 | 3 | moderate → HK "fair" |
| 4 and above | 5 | poor |

Captured frames (`:530-533`): `AA 19 00 29 02 5D …` → byte 5 = `02` (good);
`AA 19 00 1D 01 5D …` → byte 5 = `01` (excellent). Byte 6 (`5D` = 93) is not
used.

### 6.6 H7122 PM2.5: `AA 1C …`

`purifier-H7122.js:484-544` reads `bytes 4+5` as a big-endian 16-bit PM2.5 value
in µg/m³ and maps it to HomeKit `AirQuality`:

| PM2.5 (µg/m³) | `AirQuality` | Label |
| --- | --- | --- |
| ≤ 12 | 1 | excellent |
| ≤ 35 | 2 | good |
| ≤ 75 | 3 | fair |
| ≤ 115 | 4 | inferior |
| > 115 | 5 | poor |

Caveat: the inline comment at `:486` says "part 3 may be the air quality
reading" while the code actually reads parts 4+5 — treat the byte offset as
unconfirmed.

### 6.7 H7120 speed reports

`purifier-H7120.js:372-386` treats `AA 05 01 <n>` and `AA 05 02 <n>` as a gear
`n` in 1..4, then reports `n × 25 %`. Note the asymmetry with the *send* frames
in §5.5, where the gear sits in byte 3 (`33 05 01`, `33 05 02`, `33 05 03`,
`33 05 10`). Which byte a real report puts the gear in is not demonstrated by
any capture in the repo; the OpenAPI `workMode` path is the reliable read-back
for this model.

### 6.8 Diffuser

`diffuser-H7161.js:104-125` builds `deviceFunction` from bytes 1+2 (e.g.
`aa05`, `aa1b`) and has no matching case, so **every** frame is logged as
unknown and nothing is decoded. Power is the only known quantity.

---

## 7. Mode enums, speed steps, per-model quirks

### 7.1 Mode enums (OpenAPI `workMode` / `modeValue`)

| Model(s) | Enum | Reference |
| --- | --- | --- |
| H7141, H7142 | Custom = 2, Auto = 3 (gear 1–8 / 1–9 separately) | `H7141.js:10-43`, `H7142.js:15-49` |
| H7150/51/52 | Low = 1, High = 2, Auto = 3, Dryer = 8 | `dehumidifier-H7150.js:10-34` |
| H7120 | Low = 1, Medium = 2, High = 3, Sleep = 5 | `purifier-H7120.js:15` |
| H7121 | Low = 1, Medium = 2, High = 3, Sleep = **16** | `purifier-H7120.js:16` |
| H7122 | Low 1, Medium 2, High 3, Auto 4, Sleep 5, Custom 6 | `purifier-H7122.js:13-44` |
| H7123/24 | Low 1, Medium 2, High 3, Auto 4, Sleep 5 | `purifier-H7123.js:12-39` |
| H7140, H7143, H7160 | not enumerated in code (no mode frame support) | — |

`AA 05 00` wire values are a **different** enum from the API enum: `01` manual,
`02` custom, `03` auto (`H7141.js:196-216`).

### 7.2 Speed step counts

| Model | Steps | Frame level | Notes |
| --- | --- | --- | --- |
| H7140 | 8 | `33 05 01 01`–`08` | no mode support |
| H7141 | 8 | `33 05 01 01`–`08` | mode observed, not settable |
| H7142 | **9** | `33 05 01 01`–`09` | plus humidity, RGB light, UVC |
| H7143 (+aliases) | 8 | `33 05 01 01`–`08` | reports on `0501`/`0502` |
| H7160 | **9** | `33 05 01 01`–`09` | like H7142, no humidity |
| H7120/H7121 | 4 (3 gears + sleep) | byte 3: `10`,`01`,`02`,`03` | 25 % steps |
| H7122 | 5 modes | `3A 05` pairs | 20 % steps, custom not sendable |
| H7123/H7124 | 5 modes | `3A 05` pairs | 20 % steps |
| H7126 family | 3 | `33 05 01 01`–`03` | 33/66/99 % ("sleep/low/high") |
| H7150/51/52 | 8 | `33 05 01 01`–`08` | `Dryer` = 8 |
| H7161/62 | 0 | — | power only |

### 7.3 Per-model quirks worth carrying into an integration

1. **Power is `turn`, not `ptReal`.** Any implementation that assumes a
   `33 01 xx` power frame for these appliance families will send something the
   device ignores. The `33 01 01`/`33 01 00` frame belongs to the generic
   fallback handler.
2. **H7142 and H7160 add 9 speed levels; every other humidifier has 8.**
3. **H7160 deletes the humidity tile** even if a previous version created one
   (`H7160.js:43-46`); it never parses `AA 10`.
4. **H7142 auto-enables UVC on power-on** (`33 1A 01`) and there is no way to
   turn it off from HomeKit; UV state is tracked from `AA 1A 00/01`.
5. **H7142/H7160 turn the light off locally when the unit is powered off**
   (`H7142.js:182-186`, `H7160.js:130-134`) without sending a light frame.
6. **H7122/H7123 send with prefix `0x3A`** and accept reports with `0xAA` or
   `0x3A`.
7. **H7122/H7123 display-on replays the last reported `AA 16` frame** with a
   `0x33` opcode and fresh checksum, rather than sending a fixed packet.
8. **H7126 has three speeds labelled sleep/low/high** — 33 % is sleep, not low.
   Its `TargetAirPurifierState` is forced to 0 (Manual); every other purifier
   forces 1 (Auto).
9. **H7120's lowest slider step (25 %) sends `33 05 10`**, i.e. the sleep/manual
   gear 0x10 = 16, which is why H7121 (sleep = 5) is aliased to the same handler
   with a note that the sleep value "must not be sent as a shared value"
   (`purifier-H7120.js:12-17`).
10. **Diffuser decodes nothing**; `AA` frames are all "unknown" by construction.
11. **The generic handler deliberately fails** speed/mode/lock requests it does
    not understand (throws `-70402`) instead of guessing — this is the intended
    way untested models get reported (`appliance-basic.js:7-23`, `:231-248`).
12. **H7140's night-light-on brightness byte is `0x00`** because
    `this.cacheBright` is never set in that handler — likely a latent bug; send
    an explicit 0–100 value instead.
13. **H7146 has no dedicated handler alias**, so it uses the generic path.
14. Water tank never reports a refill; the plugin infers one from an off→on
    transition (`base.js:132-156`).
15. Filter change indication triggers at ≤ 10 % remaining (`base.js:100-114`).

---

## 8. SKU / model lists

`SRC/lib/utils/constants.js:774-800`:

```js
dehumidifier: ['H7150', 'H7151', 'H7152'],
humidifier: [
  'H7140', 'H7141', 'H7142', 'H7143', 'H7145', 'H7146',
  'H7147', 'H7148', 'H7149', 'H714E', 'H7160',
],
purifier: [
  'H7120', 'H7121', 'H7122', 'H7123', 'H7124',
  'H7126', 'H7127', 'H7128', 'H7129', 'H712C',
],
diffuser: ['H7161', 'H7162'],
```

Related family default controls (`SRC/lib/utils/capabilities.js:34-44`) — all four
families declare `swing: false, lock: false, light: false`, so any swing/lock
control on these devices comes only from the device's own capability report.
Model entries exist only for the diffusers: `H7161` and `H7162` are explicitly
`swing: false, lock: false, light: false` (`capabilities.js:68-71`).

---

## 9. Gaps and caveats for the HA integration

* **Target humidity is unmodelled.** No frame is known; only read-back via
  OpenAPI `humidity` → `targetHumidity`, which nothing consumes.
* **Humidity sensor is H7142-only** among humidifiers, and decodes one frame
  layout (`AA 10 <flags> <3-byte>`); H7141 emits the same layout but does not
  parse it, so the H7141 can likely report humidity with no new protocol work.
  H7160 does not send it.
* **Mode setting is unimplemented on every humidifier and on the H7150** — modes
  are only read (`AA 05 00`) or come through OpenAPI `workMode`. Only purifiers
  H7122/H7123/H7126 actually *set* a mode via a frame.
* **No timer, scheduling, display-setter (humidifiers), UV-off, or calibration
  commands are implemented**; those frames are observed and either ignored or
  only logged.
* **H7120 speed read-back byte position is unverified** (see §6.7).
* **H7122 PM2.5 byte offset is unverified** (comment vs code disagree, §6.6).
* **Air quality scales differ per model**: H7122 maps µg/m³ → 1–5, H7123 maps a
  Govee enum 1–4 → 1–5. Do not share one decoder.
* `appliance-basic` writes `openApi` commands with **no AWS frame at all**, so
  swing/lock on an unknown model requires an OpenAPI (cloud API) connection —
  they cannot work over AWS-only.
