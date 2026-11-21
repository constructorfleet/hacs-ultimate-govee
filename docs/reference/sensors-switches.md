# Govee sensors & switches — reverse-engineered protocol reference

Extracted read-only from `homebridge-govee` v11.40.0
(`2154af683e412f9a207ac6cb36d16c4340173970`, 2026-11-14).

Source root (all `path:line` references below are relative to it):
`/private/var/folders/sc/xq3g1qgx3hd0gl10w2l8rnm80000gn/T/opencode/homebridge-govee`

For a Home Assistant integration; HomeKit plumbing is deliberately omitted.

> **Read this first.** These device families do **not** send raw hex command frames over
> AWS. AWS control is a JSON envelope (`cmd`/`cmdVersion`/`data`) published to a per-device
> MQTT topic; only *reports* (and a few `ptReal` scene/zone commands used by lights) carry
> base64/hex. Where a base64 literal or hex frame exists it is quoted exactly; where the
> wire form is JSON, the exact JSON is quoted and the absence of hex is stated. Do not
> invent a hex frame for `turn`.

---

## 1. Transports and envelopes

### 1.1 AWS IoT control envelope

Built in `lib/connection/aws.js:170-178`, published in `lib/connection/aws.js:194-208`.

```json
{"msg":{"cmd":"<cmd>","cmdVersion":0,"data":{...},"transaction":"v_<epoch_ms><seq000>","type":1,"accountTopic":"<accountTopic>"}}
```

| Field | Value | Source |
|---|---|---|
| `cmd` | command name (`turn`, `brightness`, `colorwc`, `color`, `colorTem`, `ptReal`, `multiSync`) | `command-builder.js:10-46` |
| `cmdVersion` | **`0` for every control command** | `aws.js:174` |
| `data` | command payload | `aws.js:175` |
| `transaction` | `v_` + `Date.now()` + 3-digit rolling sequence (0-999) | `aws.js:187-192` |
| `type` | **`1` = control** | `aws.js:176` |
| `accountTopic` | routing only, added last | `aws.js:196-198` |

Topic: `accessory.context.awsTopic`, taken from the HTTP device record's
`deviceExt.deviceSettings.topic` (`device-context.js:137-138`).

### 1.2 AWS status request envelope

`lib/connection/aws.js:136-143`.

```json
{"msg":{"cmd":"status","cmdVersion":2,"transaction":"v_<epoch_ms><seq000>","type":0,"accountTopic":"<accountTopic>"}}
```

| Field | Value | Source |
|---|---|---|
| `cmdVersion` | **`2`** default; **`1` for H6121 only** | `device-capabilities.js:263`, `:162`; `aws.js:139` |
| `type` | **`0` = request status** | `aws.js:141` |

Retry: if a device has answered a command before and does not answer within
**5000 ms**, the identical `msg` is republished with a fresh transaction, once
(`aws.js:15-17`, `:224-252`). A reply is matched on `payload.device` +
`payload.transaction` (`aws.js:254-262`).

### 1.3 AWS inbound (report) envelope

`platform.receiveUpdateAWS` (`platform.js:1401-1414`) hands the whole payload to
`parseDeviceUpdate` (`response-parser.js:96-290`).

| Shape | Meaning | Source |
|---|---|---|
| `{device, sku, op:{command:["<b64>", ...]}}` | raw device status frames; becomes `params.commands` | `response-parser.js:269-272` |
| `{device, cmd:"status", transaction, state:{...}}` | command acknowledgement and/or state echo | `test/aws-confirm.test.js:45-51` |
| `{state:{result:...}}` with only `result` | bare command receipt, ignored (debug only) | `response-parser.js:60-66`, `platform.js:1525-1527` |
| `{cmd:"videomode", ...}` | TV/sync-box broadcast, informational only | `response-parser.js:82-86` |
| `{msg:"<json>"}` | older models wrap the payload in `msg` (JSON string) | `aws.js:81-89` |
| `{data:"<json>"}` | `data` may be a JSON string | `aws.js:91-98` |

Base64 → hex uses `Buffer.from(b64,'base64').toString('hex')`
(`functions.js:9`). `hexToTwoItems` returns an array of byte-pair strings, so
`getTwoItemPosition(hexParts, N)` is **byte N, 1-indexed** (`functions.js:55-61`).

### 1.4 BLE 20-byte frame (only where a `bleParams` exists)

`lib/utils/ble-protocol.js:1-10`, `lib/connection/ble.js:554-563`,
`lib/utils/functions.js:22-49`.

```text
33 <cmd> <data...>  00-padded to 19 bytes  <XOR of first 19 bytes>
```

| Byte | Meaning | Source |
|---|---|---|
| 0 | `0x33` outbound command marker (`0xAA` status, `0xA1` DIY, `0xA3` scene) | `ble-protocol.js:15-20` |
| 1 | command id: `0x01` power, `0x04` brightness, `0x05` colour/mode, `0x0B` segment, `0x14` gradient, `0x21` scene, `0x36` night light | `ble-protocol.js:23-31` |
| 2 | sub-command for `0x05` (e.g. `0x02` RGB default, `0x0D` RGB alt, `0x15 0x01` extended) | `ble-protocol.js:34-43` |
| 3-18 | data, zero padded | `functions.js:22-40` |
| 19 | XOR checksum over bytes 0-18 | `functions.js:35-40` |
| length | exactly 20 bytes; >19 bytes of command throws | `functions.js:29-31` |

`ptReal` BLE payloads are the raw decoded base64 bytes, **not** wrapped and not
re-checksummed (`ble.js:555-560`).

### 1.5 OpenAPI fallback

Commands with an `openApiParams` are also sent through
`POST /router/api/v1/device/control` (`openapi.js:705-720`). For switches:

| `cmd` | Capability | Value | Source |
|---|---|---|---|
| `stateOutlet` | `devices.capabilities.on_off` / `powerSwitch` | `1` / `0` from `'on'`/`'off'` | `openapi.js:632-644` |
| `stateDual` | `powerSwitch` | the raw numeric value, but only `51`/`48` are ever built | `command-builder.js:79-91`, `openapi.js:656-664` |

---

## 2. Family → handler → Home Assistant mapping

Routing table: `lib/utils/dispatch.js:30-106`. Handler registry:
`lib/device/index.js:52-132`. Default `showAs` snapshots:
`test/model-snapshot.txt`.

| Model family | Handler | HA platform (recommended) | HA entities |
|---|---|---|---|
| `switchSingle` (default) | `deviceOutletSingle` | `switch` | 1 × switch (outlet) |
| `switchSingle` + `showAs: switch` | `deviceSwitchSingle` | `switch` | 1 × switch |
| `switchSingle` + `showAs: tap` | `deviceTapSingle` | `valve` | 1 × valve (faucet) |
| `switchSingle` + `showAs: valve` | `deviceValveSingle` | `valve` | 1 × valve + duration |
| `switchSingle` + `showAs: audio/box/stick` | `deviceTVSingle` | `switch` or `media_player` | 1 × power |
| `switchDouble` (default) | `deviceOutletDouble` | `switch` | 2 × switch |
| `switchDouble` + `showAs: switch` | `deviceSwitchDouble` | `switch` | 2 × switch |
| `switchTriple` (default) | `deviceOutletTriple` | `switch` | 3 × switch |
| `switchTriple` + `showAs: switch` | `deviceSwitchTriple` | `switch` | 3 × switch |
| `rgb` + `showAs: switch` | `deviceLightSwitch` | `switch` | 1 × switch (no colour) |
| `sensorThermo` | `deviceSensorThermo` | `sensor` | temperature, humidity, battery |
| `sensorThermo` + `showExtraSwitch` | `deviceSensorThermoSwitch` | `climate` (read-only) | thermostat, humidity, battery |
| `sensorMonitor` | `deviceSensorMonitor` | `sensor` | temperature, humidity, PM2.5 |
| `sensorCO2` | `deviceSensorCO2` | `sensor` + `binary_sensor` | CO2, CO2 peak, temp, humidity, CO2 alarm |
| `sensorLeak` | `deviceSensorLeak` | `binary_sensor` + `sensor` | moisture, battery |
| `sensorPresence` | `deviceSensorPresence` | `binary_sensor` | occupancy |
| `sensorProbe` | `deviceSensorProbe` | *none* | diagnostics only |
| `sensorButton` | `GoveeSensorBasic` | *none* | diagnostics only |
| `sensorContact` | `GoveeSensorBasic` | *none* | diagnostics only |
| `sensorUnknown` | `GoveeSensorBasic` | *none* | diagnostics only |
| `template` | `deviceTemplate` | *none* | diagnostics only |

There are **no `button` or `select` entities** in any of these handlers. The only
select in the plugin belongs to light scene selectors, which are out of scope.

`showAs` legal values: `default, audio, box, cooler, heater, purifier, stick,
switch, tap, valve` (`constants.js:165-176`); single-switch variant dispatch in
`dispatch.js:117-146`.

Default `showAs: default` produces an **outlet/switch tile even for the
switchSingle family** — the snapshot for `H5001`, `H5080`, `H5081`, `H5083`,
`H5085`, `H5086`, `H5901`, `H7014` is a single `Outlet.On`
(`test/model-snapshot.txt:486-491`, `:605-640`, `:3427-3432`).

---

## 3. Switches, outlets, valves, taps, TV

### 3.1 Power command matrix (exact wire values)

All of these use AWS `cmd: "turn"`, `cmdVersion: 0`, `type: 1`, and
`data.val` = a bare integer.

| Handler / model group | On | Off | Command name | Source |
|---|---|---|---|---|
| `switchSingle` default (`H5001`, `H5081`, `H5085`, `H5086`, `H5901`, `H7014`) | `1` | `0` | `stateOutlet` → `turn` | `command-builder.js:96-109`, `device-capabilities.js:260-261` |
| **`H5080`** | **`17`** | **`16`** | `stateOutlet` → `turn` | `device-capabilities.js:140` |
| **`H5083`** | **`17`** | **`16`** | `stateOutlet` → `turn` | `device-capabilities.js:141` |
| `light-switch` (`rgb` + `showAs: switch`) | `1` | `0` | `state` → `turn` | `command-builder.js:48-69` |
| `switchDouble` gang 1 | `17` | `16` | `stateDual` → `turn` | `switch-double.js:55-58` |
| `switchDouble` gang 2 | `34` | `32` | `stateDual` → `turn` | `switch-double.js:62-64` |
| `switchDouble` both (documented only) | `51` | `48` | `stateDual` → `turn` | `switch-double.js:93-99` |
| `switchTriple` gang 1 | `17` | `16` | `stateDual` → `turn` | `switch-triple.js:28-30` |
| `switchTriple` gang 2 | `34` | `32` | `stateDual` → `turn` | `switch-triple.js:34-36` |
| `switchTriple` gang 3 | `68` | `64` | `stateDual` → `turn` | `switch-triple.js:40-42` |
| `switchTriple` all (documented only) | `119` | `112` | — | `switch-triple.js:53-54` (read path only, `:99-126`) |
| `valve` / `tap` / `TV` | `1` (`'on'`) | `0` (`'off'`) | `stateOutlet` → `turn` | `valve-single.js:86-89`, `tap-single.js:72-75`, `tv-single.js:48-51` |

Exact AWS payload for a default single outlet **on**:

```json
{"msg":{"cmd":"turn","cmdVersion":0,"data":{"val":1},"transaction":"v_1763...000","type":1,"accountTopic":"GD/..."}}
```

For `H5080`/`H5083` the only difference is `"data":{"val":17}` (off `16`).
There is **no hex or base64 form of this command** in this project.

`H5901` builds the same `turn` 1/0 payload, but has no usable AWS path and is
actuated through OpenAPI only (see §6).

Exact AWS payload for `H5082` gang 2 **on**:

```json
{"msg":{"cmd":"turn","cmdVersion":0,"data":{"val":34},"transaction":"v_1763...000","type":1,"accountTopic":"GD/..."}}
```

`stateDual` also produces an OpenAPI write, but only for `51` (both on) and `48`
(both off); per-gang values are deliberately withheld because Govee's OpenAPI
rejects them (`command-builder.js:79-91`). Since the double/triple tiles only
ever emit per-gang values, **no OpenAPI write is produced by a gang press**.

### 3.2 Light-switch frame (BLE)

`light-switch` is the handler for an RGB light shown as a switch; it removes the
`Lightbulb` service and exposes `Switch.On` (`light-switch.js:7-22`).

`state` builds both transports (`command-builder.js:48-69`):

| Transport | Exact bytes/JSON |
|---|---|
| AWS | `{"cmd":"turn","data":{"val":1}}` (off `0`), `cmdVersion 0`, `type 1` |
| BLE | `3301010000000000000000000000000000000033` (on), `3301000000000000000000000000000000000032` (off) |
| BLE base64 | `MwEBAAAAAAAAAAAAAAAAAAAAADM=` (on), `MwEAAAAAAAAAAAAAAAAAAAAAADI=` (off) |
| OpenAPI | `state` → `powerSwitch = 1/0` |

Those two base64 literals are the same ones used by `stateHeat`
(`command-builder.js:126`) and are confirmed byte-identical by decoding.

### 3.3 State reports (cloud → integration)

| Family | Field | Decode | Source |
|---|---|---|---|
| single outlet/switch (all except double) | `state.onOff` | `1` **or `17`** → `on`; anything else → `off` | `response-parser.js:127-132` |
| `switchDouble` (`H5082`, `H5089`) | `state.onOff` | `0`→`[off,off]`, `1`→`[on,off]`, `2`→`[off,on]`, `3`→`[on,on]` | `response-parser.js:112-126` |
| `switchDouble` handler | `params.state` | array of `'on'`/`'off'`, length 2 | `switch-double.js:139-154` |
| `switchSingle`/`light-switch`/outlet/valve/tap/TV | `params.state` | `'on'`/`'off'` string | `switch-single.js:76-93`, `light-switch.js:64-74`, `outlet-single.js:118-134`, `valve-single.js:135-162`, `tap-single.js:94-109`, `tv-single.js:67-79` |
| `switchTriple` | `params.stateDual` | numeric, decoded in 4 ranges (see below) | `switch-triple.js:93-163` |

Triple numeric decode (`switch-triple.js:99-162`):

| Value | Meaning |
|---|---|
| `119` | all three on |
| `112` | all three off |
| `17` / `16` | gang 1 on / off |
| `34` / `32` | gang 2 on / off |
| `68` / `64` | gang 3 on / off |

**⚠️ Read-back gap:** `parseDeviceUpdate` never emits `stateDual`. It emits
`data.state` (string or 2-array) from `state.onOff` only
(`response-parser.js:110-133`), and `platform.receiveDeviceUpdate` passes only
that parsed object to the handler (`platform.js:1503-1508`). `switch-triple`'s
`externalUpdate` therefore receives no field it acts on. In practice triple
state is command-only unless the integration decodes `onOff` itself. For a
triple device Govee reports `powerSwitch`/`onOff` as `0`/`1` (whole device), and
that maps to a scalar `'on'`/`'off'` in `response-parser.js:128-132`.

### 3.4 H5086 power metering

Only `H5086` gets Eve power characteristics and an `energy` history
(`outlet-single.js:37-68`). Frame `aa 19` (`outlet-single.js:148-174`):

| Bytes (1-indexed) | Field | Scaling |
|---|---|---|
| 1-2 | `aa 19` identifier | — |
| 9-10 | voltage | big-endian u16 ÷ 100 → V |
| 11-12 | current | big-endian u16 ÷ 100 → A |
| 13-15 | power | big-endian u24 ÷ 100 → W |
| other | ignored | — |

`CurrentConsumption` is forced to `FLOAT`, `minStep 0.01` so hundredth-watt
readings survive (`outlet-single.js:42-47`). No frame-length check is done.

### 3.5 H5089 night light (read-only)

`nightLightModels = ['H5089']` (`switch-double.js:5-10`). A `Lightbulb`
subtyped `nightlight` is added, and both `On` and `Brightness` **refuse writes**
with HAP `-70402` (`switch-double.js:69-85`, `:131-137`).

Report frame, base64/hex (`switch-double.js:156-184`):

| Bytes | Field | Decode |
|---|---|---|
| 1-3 | `aa 1b 01` | literal prefix, must match `aa1b01` |
| 4 | on/off | `01` → on, anything else → off |
| 5 | brightness | hex 1-100 → percent; outside 1-100 ignored |

Example: `aa1b010164` + zero padding → base64 `qhsBAWQAAAAAAAAAAAAAAAAAAAA=`
= on, 100 %.

### 3.6 Valves and taps

Both expose HAP `Valve` with `Active`/`InUse`/`ValveType` (`valve-single.js:29-39`,
`tap-single.js:29-37`).

| Setting | `showAs: valve` | `showAs: tap` |
|---|---|---|
| `ValveType` | `1` (irrigation) | `3` (faucet) |
| `SetDuration` | present, default **120 s** | absent |
| `RemainingDuration` | present | absent |
| Control | `stateOutlet` → AWS `turn` 1/0 | same |
| Duration sent to device? | **No** — timer is local only | n/a |
| `InUse` source | local timer / reported state | reported state |

`armTimer` closes the valve locally after `SetDuration` seconds and is re-armed
from a report if the valve is on without a timer (`valve-single.js:121-133`,
`:148-154`).

### 3.7 TV (`showAs: audio|box|stick`)

`deviceTVSingle` adds HAP `Television` with `Active` only — no input sources,
no volume, no remote keys (`tv-single.js:8-18`). `Active` on/off maps to
`stateOutlet` (AWS `turn` 1/0; OpenAPI `stateOutlet`) (`tv-single.js:27-65`).

TV backlights / sync boxes themselves are **not** this handler: `H1161`,
`H1163`, `H1168`, `H6603`, `H6608`, `H6690` etc. are in `models.rgb` and use the
light handler (`constants.js:184-186`, `:469-479`). Their video-sync broadcast is
the `videomode` payload, which is deliberately only debug-logged
(`response-parser.js:68-86`). There is no sync-mode command in the
sensor/switch scope.

### 3.8 Unsupported / skipped switch configurations

| Condition | Result | Source |
|---|---|---|
| `showAs: cooler` or `heater` without `temperatureSource` | device skipped (`needsTemperatureSource`) | `dispatch.js:125-134` |

---

## 4. Sensors

### 4.1 Thermo-hygrometer family (`sensorThermo`)

Services (`sensor-thermo.js:28-43`): `TemperatureSensor` (**primary**),
`Battery`, `HumiditySensor`. A stale `Thermostat` service is removed
(`sensor-thermo.js:24-26`).

#### Report fields and scaling

| Input | Formula | Notes | Source |
|---|---|---|---|
| `params.temperature` (HTTP `tem`, AWS, BLE) | `parseInt(temperature + offTemp) / 100` → °C | both operands are hundredths; `offTemp` is hundredths of °C | `sensor-thermo.js:86-101` |
| `state.sta.curTem` (AWS) | copied to `temperature`, same hundredths scaling | alternative AWS field some models use | `response-parser.js:209-211` |
| `state.sta.setTem` (AWS) | copied to `setTemperature` | parsed but **ignored** by this handler | `response-parser.js:216-219` |
| `params.temperatureF` | copied to `temperatureF` | parsed but **ignored** by this handler | `response-parser.js:212-214` |
| Fahrenheit display only | `cenToFar(C)` = `round((C*9/5+32)*10)/10` | never stored | `functions.js:13`; `sensor-thermo.js:96` |
| `params.humidity` (HTTP `hum`, AWS, BLE) | `parseInt(humidity + offHumi) / 100`, clamped 0-100 | `offHumi` hundredths of % | `sensor-thermo.js:104-117` |
| `params.battery` | 0-100 integer, ignored if not finite/out of range | also sets `StatusLowBattery` at `<= lowBattThreshold` (default 20) | `base.js:56-77`, `constants.js:46` |

HTTP path (`platform.js:955-973`): `deviceExt.deviceSettings.battery`,
`lastDeviceData.tem`, `lastDeviceData.hum`, `lastDeviceData.online`. The unit of
`tem` is not declared; some accounts send hundredths of °F and the code only
debug-logs the raw value (`platform.js:957-962`, `response-parser.js:201-214`).

OpenAPI path: `sensorTemperature` is in the app's unit, resolved by explicit
config, declared capability unit, or comparison with the last HTTP Celsius value
(`response-parser.js:17-48`). `sensorHumidity` is multiplied by 100
(`response-parser.js:260-263`).

BLE path: decoders yield °C/°F floats; the platform multiplies by 100 before
handing them over (`platform.js:819-825`).

#### BLE advertisement decoding

Dispatch is by marker substring and exact/`>=` length on
`manufacturerData.toString('hex')` (`validation.js:1-34`):

| Decoder | Marker | Length | Layout | Source |
|---|---|---|---|---|
| H5074 | `88ec` | **18** hex chars | temp = LE16 at chars 6-9 (two's complement) ÷ 100 °C; humidity = LE16 at 10-13 ÷ 100; battery = char 14-15 | `decode.js:5-27` |
| H5072/H5075 | `88ec` | **16** hex chars | 24-bit value at chars 6-11; bit `0x800000` = negative; temp = value/10000 °C; humidity = (value % 1000)/10; battery = chars 12-13 | `decode.js:29-56` |
| H5100/H5101/H5102 (**also H5111/H5220**) | `0100` | **>= 16** | 24-bit value at chars 8-13; same sign bit and scaling as H5075; battery = chars 14-15 | `decode.js:58-86`, `validation.js:14-30` |
| H5179 | `0188` | **22** | temp = LE16 at 12-15 (two's complement) ÷ 100; humidity = LE16 at 16-19 ÷ 100; battery = chars 20-21 | `decode.js:88-113` |

H5074 and H5075 share the `88ec` marker and are told apart by length only.
`0100` is only 4 hex digits and matches many non-sensor broadcasts, hence the
length guard (`validation.js:14-30`).

#### Freshness / precedence

A BLE reading suppresses HTTP readings for `bleRefreshTime * 4.5 * 1000` ms
(default 300 s → 1350 s) using a random key (`sensor-thermo.js:16`, `:67-81`).
The thermo-switch handler applies the same suppression
(`sensor-thermo-switch.js:16`, `:99-113`).

#### Commands

**None.** The thermo handler never calls `sendDeviceUpdate`; it is read-only.

### 4.2 Thermo sensor as a thermostat (`showExtraSwitch: true`)

`deviceSensorThermoSwitch` replaces the temperature sensor with a `Thermostat`
(`sensor-thermo-switch.js:23-38`) and keeps humidity and battery
(`:40-48`).

| Characteristic | Behaviour | Source |
|---|---|---|
| `CurrentTemperature` | live reading | `:121-133` |
| `TargetTemperature` | **mirrors current temperature**, `onGet` only | `:54-58`, `:125` |
| `CurrentHeatingCoolingState` | fixed `0` (OFF), `validValues: [0]` | `:60-65` |
| `TargetHeatingCoolingState` | fixed `0` (OFF), `validValues: [0]` | `:67-71` |
| `TemperatureDisplayUnits` | `0` = Celsius | `:73-75` |

**Setpoint commands: none exist.** There is no write path, no `onSet`, and no
AWS command builder for a target temperature in this family. `setTem` is parsed
from other devices' payloads and exposed as `data.setTemperature`
(`response-parser.js:216-219`) but this handler ignores it. An HA `climate`
entity for these models must be read-only.

The same hundredths/offset/BLE-precedence rules apply
(`sensor-thermo-switch.js:117-150`).

### 4.3 Air-quality monitor (`sensorMonitor`, H5106)

Services (`sensor-monitor.js:17-47`): `TemperatureSensor` (**primary**),
`HumiditySensor`, `AirQualitySensor` with added `PM2_5Density`.
**No battery service** — USB powered; any existing one is removed
(`sensor-monitor.js:25-33`).

#### Direct field path (HTTP device list)

| Field | Formula | Source |
|---|---|---|
| `temperature` | `parseInt(t + offTemp) / 100` °C | `sensor-monitor.js:64-78` |
| `humidity` | `parseInt(h + offHumi) / 100`, clamped 0-100 | `sensor-monitor.js:79-91` |

HTTP payload keys are `tem`, `hum`, `online`, plus `battery` (delivered but
unused) (`platform.js:975-990`).

#### Raw status frame layout (`params.commands`, i.e. AWS `op.command`)

Heuristic, not a fixed opcode (`sensor-monitor.js:94-213`):

| Byte (1-indexed) | Field | Decode |
|---|---|---|
| 1-2 | "device function" | if `0000`, `0003`, `0100`, `0101`, `0102`, `0103`, `331a`, `3315`, `aa0d`, `aa0e` → **frame ignored** (`:100-111`) |
| — | length gate | fewer than **20 bytes** → ignored (`:113-115`) |
| 1-2 | temperature | big-endian u16 hundredths °C; `round((v + offTemp/100) / 10) / 10` → 0.1 °C (`:116`) |
| — | plausibility | decoded temperature outside **-30 … 80 °C** → whole frame ignored (`:118-124`) |
| 10-11 | humidity | big-endian u16 hundredths %; `round(v/100) + offHumi/100` → **integer %** (`:141-142`) |
| 19-20 | PM2.5 | big-endian u16, µg/m³, no scaling (`:154-155`) |
| other | ignored | — |

The humidity path here rounds to a whole percent, unlike the direct-field path
which keeps two decimals. There is no clamp on the frame-path humidity.

Real test fixture (`sensor-monitor.test.js:27`, `:110-121`):

```text
hex    092e0000000000000015b800000000000000000c
base64 CS4AAAAAAAAAFbgAAAAAAAAAAAw=
=> 23.5 °C, 56 %, PM2.5 12 µg/m³
```

The guard against a command ack being read as a temperature exists because
`33 18` produced 130.8 °C (`sensor-monitor.test.js:59-72`).

#### PM2.5 → HAP AirQuality

`PM2_5Density` is the raw value; `AirQuality` is derived on every change
(`sensor-monitor.js:164-208`):

| PM2.5 (µg/m³) | HAP `AirQuality` | Label |
|---|---|---|
| 0-12 | 1 | excellent |
| >12-35 | 2 | good |
| >35-75 | 3 | fair |
| >75-115 | 4 | inferior |
| >115 | 5 | poor |

#### Commands

**None.** No setpoint, no mode, no switch.

### 4.4 CO2 monitor (`sensorCO2`, H5140)

Services (`sensor-co2.js:23-52`): `CarbonDioxideSensor` with
`CarbonDioxideLevel`, `CarbonDioxidePeakLevel`, `CarbonDioxideDetected`;
`TemperatureSensor`; `HumiditySensor`. **No battery** (mains/USB); stale service
removed.

Threshold: `co2AbnormalThreshold`, default **1000 ppm**
(`sensor-co2.js:11-21`). ⚠️ This key is **not** in
`allowed.thermoDevices` (`constants.js:120-127`) and the config parser drops
unknown per-device keys (`config-parser.js:281`), so in practice the threshold
is fixed at 1000.

#### Raw status frame: opcode `aa 0a`

Only frames whose bytes 1-2 are `aa 0a` are decoded; minimum 20 bytes
(`sensor-co2.js:68-83`).

| Byte (1-indexed) | Field | Encoding |
|---|---|---|
| 1 | `AA` | status marker |
| 2 | `0A` | live CO2/temp/humidity opcode |
| 3-4 | temperature | **little-endian** u16, hundredths °C |
| 5-6 | humidity | **little-endian** u16, hundredths %RH |
| 7-8 | CO2 | **little-endian** u16, ppm, unscaled |
| 9-20 | ignored | frame must still be >= 20 bytes |

Little-endian is assembled as `highByte||lowByte` from positions `(lsb, msb)`
(`sensor-co2.js:84-95`).

Decoding (`sensor-co2.js:90-135`):

| Field | Formula | Guard |
|---|---|---|
| temperature | `round(raw + offTemp) / 100` °C | only applied if `> -40` and `< 100` |
| humidity | `clamp(round((raw + offHumi) / 100), 0, 100)` % | integer result |
| CO2 | raw ppm | accepted if `0 … 40000` |
| peak | `max(previous peak, CO2)` | monotonic, never falls |
| detected | `1` if `CO2 >= threshold`, else `0` | default 1000 ppm |

Constructed example from the layout above (not a capture), 21.5 °C / 55.6 % /
800 ppm:

```text
hex    aa0a6608b8152003 + 12 zero bytes
base64 qgpmCLgVIAMAAAAAAAAAAAAAAAA=
```

#### Commands

**None.** Sensor only.

### 4.5 Leak / water sensors (`sensorLeak`)

Services (`sensor-leak.js:18-31`): `LeakSensor` with Eve `LastActivation`
added, and `Battery`. Battery threshold configurable
(`sensor-leak.js:13-16`).

`LeakDetected` is binary; `LastActivation` is set to
`epoch_seconds - eve_initial_time` when a leak becomes true
(`sensor-leak.js:53-64`).

#### Sources and decoding

| Source | Signal | Decode | Source |
|---|---|---|---|
| OpenAPI live | `bodyAppearedEvent` | on a **leak** SKU: `1` = wet, `2` = dry → `leakDetected = !(value - 1)` | `openapi.js:137-146` |
| HTTP device list | warning messages (`getLeakDeviceWarning`) | any unread message whose text starts `leakage alert` (whitespace-stripped, case-insensitive) | `response-parser.js:330-339` |
| HTTP device list, gateway record | `lastDeviceData.lastTime > 0` and `read === false` | unacknowledged leak, **only** when behind a gateway and **not** an `H5059`/`H5830` | `response-parser.js:297`, `:324-342` |
| AWS gateway frame | `ee34` record relayed by a WiFi gateway | 4-byte leak flag block | `platform.js:1417-1459` |

HTTP leak params: `battery` from `deviceSettings.battery`, `leakDetected`,
`online = gwonline && online` (`platform.js:920-953`).

#### Gateway `ee34` frame

`platform.js:1417-1459`:

| Hex chars (0-indexed) | Bytes | Field |
|---|---|---|
| 0-3 | 1-2 | `ee34` |
| 4-5 | 3 | subdevice number (decimal via parseInt base 16) |
| 6-7 | 4 | record type; **only `02` (live status) accepted** |
| 8-17 | 5-9 | `00 64 1e 14` + sequence |
| 18-25 | 10-13 | Unix time, big-endian u32 |
| 26-33 | 14-17 | leak flags; `!= "00000000"` → wet |
| 34+ | 18+ | `80 00` + checksum |

Gates: minimum 36 hex chars, type `02`, and `|now - recordTime| <= 600 s`;
other records during periodic sync are debug-only (`platform.js:1427-1443`).
The update is delivered only when `gatewayDevice === payload.device` **and**
`gatewaySno === subdeviceNo` **and** the model is in `sensorLeak`
(`platform.js:1446-1456`).

#### Commands

None. No `stateOutlet`/`turn` is ever sent by this handler.

### 4.6 Presence sensor (`sensorPresence`, H5127)

Service: `OccupancySensor` only (`sensor-presence.js:9-11`). No battery.

| Source | Decode | Source |
|---|---|---|
| OpenAPI `bodyAppearedEvent` | for presence SKUs: `1` → occupied, anything else → clear | `openapi.js:137-145` |
| `params.presenceDetected` | truthy → 1, else 0 | `sensor-presence.js:18-22`, `response-parser.js:193-196` |
| AWS frame `aa 01` | byte 3 `=== 01` → occupied, anything else → clear | `sensor-presence.js:36-42` |

Any other `aa..` frame is logged as unknown; non-`aa` frames are ignored
(`sensor-presence.js:29-51`).

Constructed examples: `aa0101`+pad → `qgEBAAAAAAAAAAAAAAAAAAAAAAA=`
(occupied), `aa0100`+pad → `qgEAAAAAAAAAAAAAAAAAAAAAAAA=` (clear).

#### Commands

None.

### 4.7 Probe thermometers (`sensorProbe`) — undecoded

`deviceSensorProbe` deliberately exposes **nothing**. It removes
`TemperatureSensor`, `HumiditySensor` and `Battery` left by older versions
(`sensor-probe.js:22-25`) and logs every raw command plus every non-command
field as `kind: "probe reading"` / `"probe update"` (`sensor-probe.js:31-51`).
There is no temperature decode, no probe indexing, no scaling.

Historical note: the H5198 was once given ordinary thermometer tiles and showed
one probe of four stuck at its starting value (`sensor-probe.js:5-17`).

### 4.8 Undecoded sensors and templates

| Handler | Models | Behaviour |
|---|---|---|
| `deviceSensorBasic` | `sensorButton` (H5122), `sensorContact` (H5023/H5123), `sensorUnknown` (H5026/H5130) | no services; logs each `params.commands` entry as `kind: "reading"` with raw base64 + hex, and each other field as `kind: "update"` (`sensor-basic.js:12-42`) |
| `deviceTemplate` | `template` list | no services; logs the whole payload as `kind: "payload"`, then each `aa..` frame as `kind: "status"`; all other frames are dropped (`template.js:6-47`) |

Test fixture for the basic handler (`sensor-basic.test.js:25`):

```text
base64 qgUBAgAAAAAAAAAAAAAAAAAAAKw=
hex    aa050102000000000000000000000000000000ac
```

There is no contact open/close decode and no button-event decode in this
project. Do not assume `aa05` means contact — the handler does not interpret it.

---

## 5. Enums, ranges, defaults

| Constant | Value | Source |
|---|---|---|
| `awsPowerOn` / `awsPowerOff` default | `1` / `0` | `device-capabilities.js:260-261` |
| H5080 / H5083 power | `17` / `16` | `device-capabilities.js:140-141` |
| Double gang values | `17/16`, `34/32`, `51/48` | `switch-double.js:93-99` |
| Triple gang values | `17/16`, `34/32`, `68/64`, `119/112` | `switch-triple.js:53-63`, `:99-162` |
| `awsStatusCmdVersion` default | `2` | `device-capabilities.js:263` |
| H6121 status version | `1` | `device-capabilities.js:162` |
| Control `cmdVersion` | `0` | `aws.js:174` |
| AWS `type` | `0` status request, `1` control | `aws.js:141`, `:176` |
| Command confirm timeout | 5000 ms, one retry | `aws.js:15-17`, `:224-252` |
| `lowBattThreshold` default / min | `20` / `1`; clamped to ≤100 | `constants.js:46`, `:59`; `sensor-thermo.js:19-21` |
| BLE refresh default | 300 s | `constants.js:41` |
| Thermo BLE-over-HTTP window | `bleRefreshTime * 4.5 * 1000` ms | `sensor-thermo.js:16`, `:67-81` |
| CO2 abnormal threshold | 1000 ppm (effectively fixed) | `sensor-co2.js:14`, `:20-21` |
| CO2 accepted range | 0-40000 ppm | `sensor-co2.js:116` |
| CO2 temperature range | -40 … 100 °C | `sensor-co2.js:101` |
| Monitor temperature range | -30 … 80 °C (frame path) | `sensor-monitor.js:122` |
| Monitor frame minimum | 20 bytes | `sensor-monitor.js:113` |
| Valve `SetDuration` default | 120 s | `valve-single.js:36` |
| Valve `ValveType` | `1` valve, `3` tap | `valve-single.js:35`, `tap-single.js:35` |
| PM2.5 bands | 12 / 35 / 75 / 115 µg/m³ | `sensor-monitor.js:168-208` |
| BLE packet size | 20 bytes, XOR of first 19 | `ble-protocol.js:68`, `functions.js:29-40` |
| BLE `33 18` command ack | not in the ignore list; rejected only by the -30…80 °C plausibility guard | `sensor-monitor.js:116-124` |
| `showAs` allowed | `default,audio,box,cooler,heater,purifier,stick,switch,tap,valve` | `constants.js:165-176` |

---

## 6. Per-model quirks

| Model | Quirk | Source |
|---|---|---|
| `H5080`, `H5083` | AWS power uses `17`/`16`, not `1`/`0`; reports also arrive as `17` for on | `device-capabilities.js:140-141`, `response-parser.js:128-132` |
| `H5082`, `H5089` | Double switch/outlet: reports use a 2-bit `onOff` (`0-3`), commands use `17/16/34/32` | `response-parser.js:112-126`, `switch-double.js:55-67` |
| `H5089` | Has a night light; `aa1b01 [state] [level]` is read correctly but **all light writes are refused** (`-70402`); service left over from a single-outlet setup is removed | `switch-double.js:5-10`, `:27-30`, `:69-85`, `:131-184` |
| `H5160`, `H5161` | Share a goodsType; triple. `H5161` mapped to the same handler | `constants.js:684-686` |
| `H5085` | Listed under `switchSingle`, but the UI maps it to `switchDevices` and describes it as a dual smart plug | `homebridge-ui/server.js:36-38`, `constants.js:678` |
| `H5086` | Only switch with power metering (`aa19`); watt is a 3-byte value ÷100 | `outlet-single.js:37-68`, `:149-155` |
| `H5901` | Water timer; **OpenAPI only** — no usable AWS/BLE/LAN path; requires an API key; `showAs: valve|tap` recommended | `constants.js:670-672` |
| `H5106` | USB powered, **no battery**; frame parser is heuristic; ignores `33 1a`, `33 15`, `aa 0d`, `aa 0e` and short frames | `sensor-monitor.js:25-33`, `:100-124` |
| `H5140` | USB powered, no battery; only `aa 0a` frames decoded | `sensor-co2.js:46-52`, `:77-82` |
| `H5059`, `H5830` | Gateway leak sensors; the cloud record `read` flag is **not** used (app judges probes instead) | `response-parser.js:297`, `:341` |
| `H5058` | Gateway leak sensor; **is** allowed to use the unread-record flag | `response-parser.js:341` |
| `H5183` | A meat thermometer but stays on `sensorThermo` because its existing tiles have never been reported wrong | `constants.js:720-724` |
| `H5127` | Presence; `bodyAppearedEvent` must be read as presence, not leak | `openapi.js:137-145` |
| `H5122` | Button; nothing decoded, reports only | `constants.js:810`, `dispatch.js:100` |
| `H5023`, `H5123` | Contact; nothing decoded, reports only | `constants.js:811`, `dispatch.js:101` |
| `H5026`, `H5130` | Unknown sensors; reports only | `constants.js:812-814`, `dispatch.js:102` |
| `H5111`, `H5220` | Documented as sharing the H5101 BLE broadcast; validator uses `>= 16` to allow longer payloads | `constants.js:708`, `:716`; `validation.js:23-30` |
| `H5074` vs `H5075` | Same `88ec` marker, different lengths (18 vs 16 hex chars) | `validation.js:1-12` |
| `H6121` | Status requests need `cmdVersion: 1` (light model; cross-cutting status-request quirk) | `device-capabilities.js:162` |
| `H3001` | BLE-only solar string lights; AES-128-GCM v2 wrapper required; not a switch/sensor but appears near these lists | `device-capabilities.js:146-159` |

### Unsupported/undecoded by design

- All `sensorProbe` models: **no entities**, raw logging only (`sensor-probe.js:18-51`).
- All `sensorButton`, `sensorContact`, `sensorUnknown`, `template` models:
  **no entities**, raw logging only (`sensor-basic.js:12-42`, `template.js:6-47`).
- `showAs: cooler|heater` without `temperatureSource`: device is skipped
  (`dispatch.js:125-134`).

---

## 7. SKU lists (verbatim from `lib/utils/constants.js`)

### 7.1 `switchSingle` — `constants.js:673-682`

```text
H5001, H5080, H5081, H5083, H5085, H5086, H5901, H7014
```

### 7.2 `switchDouble` — `constants.js:683`

```text
H5082, H5089
```

### 7.3 `switchTriple` — `constants.js:686`

```text
H5160, H5161
```

### 7.4 `sensorLeak` — `constants.js:687`

```text
H5054, H5058, H5059, H5830
```

### 7.5 `sensorThermo` — `constants.js:688-719`

```text
B5178, H5051, H5052, H5053, H5055, H5071, H5072, H5074, H5075, H5100,
H5101, H5102, H5103, H5104, H5105, H5107, H5108, H5109, H5110, H5111,
H5112, H5171, H5174, H5177, H5179, H5183, H5190, H5220, H5310, R5112
```

### 7.6 `sensorProbe` — `constants.js:728-740`

```text
H5181, H5182, H5184, H5185, H5191, H5192, H5194, H5196, H5198, H5199, H5610
```

### 7.7 `sensorMonitor` — `constants.js:741`

```text
H5106
```

### 7.8 `sensorCO2` — `constants.js:742`

```text
H5140
```

### 7.9 `sensorPresence` — `constants.js:815`

```text
H5127
```

### 7.10 `sensorButton` — `constants.js:810`

```text
H5122
```

### 7.11 `sensorContact` — `constants.js:811`

```text
H5023, H5123
```

### 7.12 `sensorUnknown` — `constants.js:814`

```text
H5026, H5130
```

### 7.13 `template` — `constants.js:823-837`

```text
H1162, H1167, H5010, H5024, H5042, H5043, H5121, H5124, H5126, H5129, H5125
```

> `composter: ['H7184']` (`constants.js:726`) sits between the probe and monitor
> lists and is routed to `deviceComposterBasic` (`dispatch.js:61`), out of scope
> here.

---

## 8. Gaps and caveats for the HA implementation

1. **No hex control frames for switches.** AWS control is JSON `turn`; there is no
   captured raw `33 xx` power frame for any switch/outlet model in this project.
   The only switch-relevant hex frames are BLE `light-switch` power
   (`33 01 01/00`) and the `ptReal` night-light/zone frames used by lights.
2. **Triple read-back is not wired.** `switch-triple.js:93-163` reads
   `params.stateDual`, but `parseDeviceUpdate` never produces it. HA must decode
   `onOff` (0/1 whole-device or 0-3 for double only) or poll a different field.
3. **Double reports are a 2-bit field**, not two separate booleans, and the
   command encoding (`17/16/34/32`) is unrelated to the report encoding (`0-3`).
4. **Thermostat and monitor setpoints do not exist here.** No handler in this
   document writes `setTem`/`targetTemperature` (heaters elsewhere do, via
   OpenAPI); `TargetTemperature` mirrors the current reading and both
   heating/cooling states are pinned to OFF.
5. **`co2AbnormalThreshold` is unreachable via config.** It is read by
   `sensor-co2.js:20-21` but absent from the allowed-key list and removed by the
   config parser, so the threshold is always 1000 ppm unless HA supplies its own.
6. **Monitor humidity has two different scalings:** direct field = two decimals,
   frame path = rounded integer; neither clamps the frame path.
7. **Monitor temperature is heuristic.** Any 20+ byte frame not in the ignore
   list is treated as temperature, with only a -30…80 °C plausibility guard.
   Frames with a plausible leading u16 but unrelated content will be misread.
8. **Battery is absent by design** on H5106 and H5140; adding a battery entity
   would reproduce the permanent "Battery Low" bug the code removes
   (`sensor-monitor.js:25-33`, `sensor-co2.js:46-52`).
9. **Leak state is three different mechanisms** (OpenAPI event, cloud warning
   messages, cloud record `read` flag) plus a gateway-only `ee34` frame. None of
   them is a direct sensor-level leak frame.
10. **`sensorThermo4` is a dead category name** referenced only by the UI model
    map (`homebridge-ui/server.js:16`); there is no `models.sensorThermo4`.
11. **H5901 needs the OpenAPI**; an AWS-only implementation will look online but
    never actuate.
12. **Buttons/contacts/probes are genuinely undecoded.** Their frames are logged,
    not interpreted; the `aa05` fixture is not a contact-state decode.
13. The H5086 power frame has no length check, so a short `aa19` frame can yield
    undefined/garbage values in the reference implementation; HA should enforce
    ≥ 15 bytes before reading wattage.
