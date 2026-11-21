# Fans, Heaters, Ice Makers and Kettles — wire protocol reference

Reverse-engineered from the [`homebridge-govee`](https://github.com/homebridge-plugins/homebridge-govee) JavaScript
implementation. Everything below is taken from the handlers named in each section; nothing is inferred from the
Govee app or from undocumented captures unless the source comment says so. Line references are to that project's
files (`lib/device/...`, `lib/utils/...`).

Scope: the appliance handlers `fan-H7100.js`, `fan-H7105.js`, `fan-H7107.js`, `fan-ceiling.js` (plus the base
`fan-H1370.js` it subclasses), `heater1a.js`, `heater1b.js`, `heater2.js`, `heater-single.js`,
`cooler-single.js`, `ice-maker-H7172.js`, `kettle.js`, and the shared helpers `device-capabilities.js`,
`capabilities.js`, `constants.js`, `command-builder.js`, `response-parser.js`.

> Verified while writing: every base64 literal quoted here was decoded to hex, and every checksum was
> re-computed as `XOR(bytes 1..19)`. All matched.

---

## 0. Family / handler / HA-layer summary

| Family | SKUs | Handler actually used | Suggested HA layer |
|---|---|---|---|
| Tower fan, 8-speed | H7100, H7101, H7102, H7106, H7111 | `deviceFanH7100` (`fan-H7100.js`) | `fan` |
| Tower fan, 12-speed | H7105, H7107 | `deviceFanH7105`, `deviceFanH7107` | `fan` + (`light` for both, `sensor` temp for H7107) |
| Ceiling fan + two lights | H1310, R1310, H1370 | `deviceFanCeiling` (`fan-ceiling.js` → base `fan-H1370.js`) | `fan` + `light` (main, shared brightness/CT) + `light` (background, on/off) |
| Fan, undecoded | H7103, H7112 | `deviceFanBasic` (`appliance-basic.js`) | `fan` power only; speed must be reported, not sent |
| Heater, fan tile | H7130, H713A, H713C, H7137, H713E | `deviceHeater1A` **or** `deviceHeater1B` (chosen at dispatch) | `fan` + switches |
| Heater, thermostat tile | same heater1 list | `deviceHeater1B` | `climate` + `fan` + switches |
| Heater, full | H7131, H7132, H7133, H7134, H7135, H713B | `deviceHeater2` | `climate` + `fan` + `light` + switches |
| Smart-plug pretending to be heater/cooler | any `switchSingle` SKU with `showAs: heater/cooler` | `deviceHeaterSingle`, `deviceCoolerSingle` | `climate` (external temperature source) |
| Ice maker | H7172, H717D, H8120, H8121, H8122 | `deviceIceMakerH7172` | `switch` + `select` (ice size) + `light` (capability-gated) |
| Ice maker, undecoded | H8102, H8131 | `deviceIceMakerBasic` | `switch` power only |
| Kettle | H7170, H7171, H7173, H7175, H717A | `deviceKettle` | `button`s + `binary_sensor`s + `sensor`s |

Dispatch table: `lib/utils/dispatch.js:65-105`, handler map `lib/device/index.js:52-132`.

SKU lists (`lib/utils/constants.js`):

| List | SKUs | Source |
|---|---|---|
| `fan` | H1310, H1370, H7100, H7101, H7102, H7103, H7105, H7106, H7107, H7111, H7112, R1310 | `constants.js:743-756` |
| `heater1` | H7130, H713A, H713C, H7137, H713E | `constants.js:757-763` |
| `heater2` | H7131, H7132, H7133, H7134, H7135, H713B | `constants.js:764-773` |
| `iceMaker` | H7172, H717D, H8102, H8120, H8121, H8122, H8131 | `constants.js:801-809` |
| `kettle` | H7170, H7171, H7173, H7175, H717A | `constants.js:816-822` |

Notes on the dispatch:

- `fan` uses a prefix lookup `deviceFan<SKU>` with fallback `deviceFanBasic` (`dispatch.js:66-73`, `189-191`).
  H7103 and H7112 therefore get **power only** and a speed slider that reports "not supported" rather than
  sending a guess.
- `heater1` never uses a per-model handler: `chooseHeater` returns `deviceHeater1B` when the device says it has
  `sensorTemperature`, or a previous run learnt `supportsAmbientTemp`, or the owner set `tempReporting`;
  otherwise `deviceHeater1A` (`dispatch.js:156-163`).
- `iceMaker` uses `deviceIceMaker<SKU>` with fallback `deviceIceMakerBasic`; H8102 and H8131 fall back.
- Polling: `heater1` and `heater2` poll every cycle; `fan` polls only H7107; `iceMaker` and `kettle` do not
  poll — `dispatch.js:69-75`, `103-104`.

---

## 1. Frame format

Every raw code is a 20-byte packet, base64-encoded for transport:

```
byte  1     2     3     4 .. 19                20
      ID    CMD   SUB   data, zero-padded       XOR of bytes 1..19
```

Builder: `generateCodeFromHexValues` (`lib/utils/functions.js:22-44`). BLE and AWS both take the same bytes;
AWS takes them as a base64 string inside `msg.data.command[]`.

Conventions used below:

- All byte positions are **1-based**, matching `getTwoItemPosition(hexParts, n)` (`functions.js:55`).
- `…` means "zero padding to byte 19, then checksum".
- Report frames start `aa`; commands usually start `33` (ptReal) or `3a` (multiSync). This is the device's own
  convention, not the AWS command name — heater2 sends several `33`-prefixed frames under `cmd: multiSync`
  (§4.2).
- `aa` codes are decoded by splitting the base64 into hex bytes and looking at byte 2 (and sometimes byte 3)
  as an identifier (`base64ToHex` → `hexToTwoItems`, `functions.js:9`, `61`).

Examples (full packets, verified):

| Meaning | Hex | Base64 |
|---|---|---|
| Universal power on | `33 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 33` | `MwEBAAAAAAAAAAAAAAAAAAAAADM=` |
| Universal power off | `33 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 32` | `MwEAAAAAAAAAAAAAAAAAAAAAADI=` |

---

## 2. AWS IoT transport

### 2.1 Envelope for a command

`lib/connection/aws.js:163-185`:

```json
{
  "msg": {
    "cmd": "ptReal",
    "cmdVersion": 0,
    "data": { "command": ["<base64 frame>"] },
    "transaction": "v_<epoch-ms><seq 000-999>",
    "type": 1,
    "accountTopic": "<account topic>"
  }
}
```

- `cmdVersion` is **0 for every command**, always (`aws.js:173`).
- `type` is 1 for a command, 0 for a status request.
- `transaction` is `v_` + `Date.now()` + a 3-digit sequence (`aws.js:187-192`).
- Topic is the device's `awsTopic` from the account login; `accountTopic` is appended for routing only
  (`aws.js:194-208`).
- Commands are re-sent once if the device has answered a command before and does not acknowledge within
  `CONFIRM_MS` (`aws.js:210-252`). This matters for idempotency: the frames are absolute, not toggles, so a
  retry is safe.

### 2.2 Envelope for a status request

`aws.js:129-161`:

```json
{ "msg": { "cmd": "status", "cmdVersion": 2, "transaction": "v_…", "type": 0 } }
```

`cmdVersion` comes from `getDeviceCapabilities(model).awsStatusCmdVersion`, default **2**, overridden to **1**
for H6121 only (`device-capabilities.js:161-162`, `263`).

### 2.3 High-level `cmd` names → AWS command

`buildCommand` (`lib/utils/command-builder.js:10-46`) maps the handlers' names:

| Handler `cmd` | AWS `msg.cmd` | AWS `msg.data` | Used by |
|---|---|---|---|
| `ptReal` | `ptReal` | `{ command: [frame] }` | fans, heater1, ice maker, kettle |
| `multiSync` | `multiSync` | `{ command: [frame] }` | H7105/H7107 night light + swing, heater2, ice night-light colour |
| `stateHeat` | `multiSync` (frame is `33 01 01`/`33 01 00`) | `{ command: [frame] }` | heater2 power (`command-builder.js:125-140`) |
| `stateOutlet` | `turn` | `{ val: 1 }` / `{ val: 0 }` | heater-single / cooler-single |
| `brightness` | `brightness` | `{ val: 0-100 }` (or `0-254` if the model scales) | ceiling-fan light |
| `color` | `colorwc` by default (`color` / `redgreenblue` if configured) | `{ color:{r,g,b}, colorTemInKelvin:0 }` | ceiling-fan light |
| `colorTem` | `colorwc` by default | `{ color, colorTemInKelvin }` | ceiling-fan light |
| `openApi` | *no AWS* — OpenAPI HTTP call only | — | capability-gated controls |

`stateOutlet` uses `caps.awsPowerOn` / `caps.awsPowerOff` — 1/0 by default, **17/16** on H5080 and H5083
(`device-capabilities.js:139-141`, `command-builder.js:96-109`). `stateHeat` is the same frame as universal
power-on/off but is sent as `multiSync` (`command-builder.js:125-140`).

### 2.4 Status payload

A status arrives with `source: 'AWS'` and the raw message spread at the top level (`platform.js:1401-1409`).
`parseDeviceUpdate` (`lib/utils/response-parser.js:96-290`) flattens it:

| Payload field | Normalised field | Meaning |
|---|---|---|
| `state.onOff` | `state` (`'on'`/`'off'`) | 1 or **17** is on; anything else off (`response-parser.js:111-133`) |
| `state.brightness` | `brightness` 0-100 | divided by 2.54 only for the 254-scale models (`:136-151`) |
| `state.color` | `rgb` | ceiling-fan light |
| `state.colorTemInKelvin` | `kelvin` | clamped 2000-7143 K upstream (`:159-165`) |
| `state.sta.curTem` | `temperature` | hundredths of a degree **Fahrenheit** (`:201-211`) |
| `state.sta.setTem` | `setTemperature` | hundredths of a degree **Fahrenheit** (`:217-219`) |
| `state.workMode` | `workMode` | `{ workMode, modeValue }` |
| `state.toggles` | `toggles` | `{ oscillationToggle, lockToggle, … }` booleans |
| `state.targetTemperature` | `targetTemperature` | number or `{ temperature }` |
| `state.sensorTemperature` | `temperature` | converted to hundredths °C after unit resolution (`:246-258`) |
| `op.command` | `commands[]` | **array of base64 status frames** (`:265-272`) |
| `op.mode` + array `op.value` | `commands[]` | some legacy mode reports (`:273-275`) |
| `op.opcode === 'mode'` + `op.modeValue[]` | `commands[]` | (`:276-279`) |
| `bulb` | `commands[]` | legacy devices (`:280-282`) |

Every handler iterates `params.commands`, converts each with `base64ToHex`, and ignores anything whose byte 1
is not `aa` (`fan-H7100.js:253-261`, `heater1a.js:353-363`, etc.).

---

## 3. Tower fans

### 3.1 H7100 / H7101 / H7102 / H7106 / H7111 — 8 speeds

Handler: `lib/device/fan-H7100.js`. Entity: Fanv2 with `Active`, `RotationSpeed` (0-100 %, minStep 1) and
`SwingMode`. No light service.

Documented app modes (`fan-H7100.js:13-23`): H7100/H7102/H7106 → Sleep, Nature, Custom, Auto; H7101 →
Sleep, Nature, Turbo, Custom, Auto; H7111 → Sleep, Nature, Custom, Auto. Only **speed** and **auto** are
implemented; Sleep/Nature/Custom/Turbo have no frames here.

#### Capabilities

| Capability | Value |
|---|---|
| Power | `Active` 0/1 |
| Speed steps | **8** real speeds, excluding auto (`fan-H7100.js:44-46`) |
| Auto | pseudo-step **9** (`autoSpeed`), reported as 100 % |
| Oscillation | `SwingMode` on/off |
| Light / temp / direction / lock | none |

#### Write frames (`cmd: ptReal`)

| Function | Hex template | Exact literals | Source |
|---|---|---|---|
| On | `33 01 01` | `MwEBAAAAAAAAAAAAAAAAAAAAADM=` | `fan-H7100.js:118-121` |
| Off | `33 01 00` | `MwEAAAAAAAAAAAAAAAAAAAAAADI=` | same |
| Speed 1-8 | `33 05 01 <01-08>` | `MwUBAQ…ADY=`, `MwUBAg…ADU=`, `MwUBAw…ADQ=`, `MwUBBA…ADM=`, `MwUBBQ…ADI=`, `MwUBBg…ADE=`, `MwUBBw…ADA=`, `MwUBCA…AD8=` (full bytes in §3.4) | `fan-H7100.js:33-41` |
| Auto | `33 05 00 03` | `MwUAAwAAAAAAAAAAAAAAAAAAADU=` | `fan-H7100.js:42` |
| Swing on | `33 1f 01 01` | `Mx8BAQAAAAAAAAAAAAAAAAAAACw=` | `fan-H7100.js:191` |
| Swing off | `33 1f 01 00` | `Mx8BAAAAAAAAAAAAAAAAAAAAAC0=` | same |

Percent → step: `step = max(1, min(8, round(pct * 8 / 100)))` (`functions.js:145-147`). Step → percent:
`min(100, round(step / 8 * 100))`, with auto → 100 (`functions.js:183-191`). Auto is **not reachable** from
the slider: 100 % maps to step 8.

#### OpenAPI mirror (sent alongside the raw frame when advertised)

`fan-H7100.js:154-167`, `189-199`:

- speed: `{ instance: 'workMode', type: 'devices.capabilities.work_mode', value: { workMode: 1, modeValue: step } }`
- auto: `value: { workMode: 3 }`
- oscillation: `{ instance: 'oscillationToggle', type: 'devices.capabilities.toggle', value: 1|0 }`

#### Report frames (`aa`)

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 05 01 <1-8>` | fan speed | byte 4 hex, accepted only in 1..8 | `fan-H7100.js:273-283` |
| `aa 05 00 03` | auto mode | byte 4 == `03` → cache auto, show 100 % | `fan-H7100.js:284-293` |
| `aa 1f 01 <0/1>` | oscillation | byte 4 == `01` = on | `fan-H7100.js:294-318` |
| `aa 08 xx xx xx xx xx xx …` | sensor attached | bytes 3-8 != `000000000000` → `sensorAttached` | `fan-H7100.js:263-268` |
| anything else | logged as unknown | — | `fan-H7100.js:319-326` |

`aa 1f 01` is only interpreted when `caps.readsSwingStatus` is true (default true). If false, the frame is
reported as unknown instead, which is how a model gets confirmed (`fan-H7100.js:30`, `294-306`;
`device-capabilities.js:265`, `107-123`).

#### Quirks

- A restored HomeKit percentage is converted back to a step at startup; a restored 100 % is deliberately
  treated as top speed, not auto (`fan-H7100.js:84-93`).
- `internalSwingUpdate` compares the cached **string** `'on'`/`'off'` against the boolean-ish `value`, so it
  always sends; harmless but noisy.
- Auto is reported by the device but cannot be commanded by this handler.

### 3.2 H7105 / H7107 — 12 speeds, night light, swing range (H7107 also temperature)

Handlers: `lib/device/fan-H7105.js`, `lib/device/fan-H7107.js`. Both build Fanv2, an optional `Lightbulb`
(`hideLight` config suppresses it), and H7107 additionally a `TemperatureSensor` created on first reading.
Both set the fan as the primary service (`fan-H7107.js:62-65`).

#### Capabilities

| Capability | H7105 | H7107 | Source |
|---|---|---|---|
| Power | yes | yes | `fan-H7105.js:159-162` |
| Speed steps | **12** | **12** | `fan-H7105.js:41-42` |
| Auto | pseudo-step **13** | 13 | `:38-40` |
| Oscillation | on/off + range bytes | on/off + range bytes | `:220-279` |
| Night light | on/off, brightness 0-100, RGB | same | `:281-409` |
| Room temperature | no | yes (`aa 10`) | `fan-H7107.js:428-455` |
| Direction / lock | no | no | — |

#### Write frames

| Function | Hex template | Exact literals / notes | Source |
|---|---|---|---|
| On / Off | `33 01 01` / `33 01 00` | `MwEB…ADM=` / `MwE…ADI=` | `fan-H7105.js:159-162` |
| Speed 1-12 | `33 05 01 <01-0c>` | `MwUBAQ…ADY=` … `MwUBDA…ADs=` | `fan-H7105.js:25-37` |
| Auto | `33 05 00 02` | `MwUAAgAAAAAAAAAAAAAAAAAAADQ=` | `fan-H7105.js:38` |
| Swing on | `33 1d 01 <range b4-b7>` | range bytes come from the last `aa 1d` report, bytes 4-7; e.g. `33 1d 01 01 96 03 84` | `fan-H7105.js:235-245` |
| Swing off | `33 1d 00` | no range bytes on purpose | same |
| Swing on (multiSync) | `3a 1d 01 <range>` | duplex send, same bytes with `3a` | `fan-H7105.js:257-265` |
| Light on/off | `3a 1b 01 01 <0/1>` | full `3a 1b 01 01 01` on / `… 00` off | `fan-H7105.js:291-297` |
| Light brightness | `3a 1b 01 02 <0-100>` | 0 is treated as "off" after 1.5 s | `fan-H7105.js:333` |
| Light colour | `3a 1b 05 0d RR GG BB` | RGB from HS | `fan-H7105.js:388` |

All night-light writes are `cmd: multiSync`. `hkPercentToFanSpeed`/`fanSpeedToHkPercent` use 12 steps.

#### Report frames

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 05 01 <1-12>` | fan speed | byte 4; **no bounds check and no % conversion** | `fan-H7105.js:469-479` |
| `aa 05 00 02` | auto | byte 4 == `02` → auto, 100 % | `fan-H7105.js:480-489` |
| `aa 1b 01 <0/1> <bright>` | light on/off + brightness | byte 4 = state, byte 5 = 0-100 | `fan-H7105.js:490-509` |
| `aa 1b 05 0d RR GG BB` | light colour | bytes 5-7 = RGB (byte 4 ignored) | `fan-H7105.js:510-533` |
| `aa 1d 00 <range b4-b7>` | swing off | stores the whole frame as `cacheSwingCode` | `fan-H7105.js:534-544` |
| `aa 1d 01 <range b4-b7>` | swing on | same, caches range | `fan-H7105.js:545-555` |
| `aa 08 …` | sensor attached | bytes 3-8 | `fan-H7105.js:459-464` |
| `aa 10 <flags> <3-byte reading>` | room temperature (H7107 only) | see below | `fan-H7107.js:512-522` |

H7107 temperature: bit 7 of the flags byte marks a reading from the fan's own sensor; `0xffffff` means no
reading. The 3-byte value is `°F × 10000` with bit 23 as sign. Decode (`fan-H7107.js:428-455`):

```
negative = (reading & 0x800000) != 0
size     = floor((reading & 0x7FFFFF) / 1000)      // tenths of °F
tenthsF  = negative ? -size : size
celsius  = round(((tenthsF/10 - 32) / 1.8) * 10) / 10
```

Example from the source: `0x0aad98` = 699800 → 69.9 °F → 21.1 °C. H7107 is polled over AWS because it only
sends this reading occasionally (`dispatch.js:69-72`).

#### Quirks

- **H7105/H7107 status bug**: `aa 05 01 <n>` writes the raw step straight into `RotationSpeed`, so step 6 is
  shown as 6 %, not 50 % (`fan-H7105.js:475`, `fan-H7107.js:533`). The send path does convert correctly.
  H7100 does convert on read; the ceiling fan does too. Worth fixing in a port rather than copying.
- Swing ON must carry the range bytes; swing OFF must not — a parameterised OFF was answered with a zero-tailed
  frame while the fan kept oscillating (#1334/#1339, `fan-H7105.js:230-235`).
- The `3a 1d` multiSync duplicate exists because the fan's own oscillation traffic uses that shape;
  whichever the model ignores is harmless (`fan-H7105.js:255-265`).
- H7107 auto is `33 05 00 02`, not `03` like the H7100 family.

### 3.3 Ceiling fans H1310 / R1310 / H1370

Handler: `lib/device/fan-ceiling.js`, subclassing `fan-H1370.js` (the base is a single-light fallback and no
model is mapped to it directly — `fan-H1370.js:17-34`).

All three models speak the same language, settled by labelled captures:

- `aa 36 <main> <background>` = **the two lights** (not the fan).
- `aa 42 <mask>` = the same lights as a bitmask.
- `aa 31 <running> <speed> <direction> 00 00 00 <oscillation>` = the **fan**, including direction and
  oscillation.

Source: `fan-ceiling.js:13-91`, `fan-H1370.js:26-33`.

#### Capabilities

| Capability | H1310 / R1310 | H1370 | Source |
|---|---|---|---|
| Power | via OpenAPI `fanToggle`, else `33 31 <on> <speed>` | same | `fan-ceiling.js:235-275` |
| Speed steps | **6** | **12** | `device-capabilities.js:121-123` |
| Speed steps (live source) | max option value in OpenAPI `fanSpeedMode` | same | `functions.js:162-173` |
| Oscillation | none | yes, **OpenAPI only** (`fanOscillateToggle`) | `fan-ceiling.js:158-172` |
| Direction | OpenAPI `reverseAirflowToggle` | same | `fan-ceiling.js:174-192` |
| Lights | main + background, each OpenAPI on/off | same | `fan-ceiling.js:194-221` |
| Shared light controls | one brightness + one colour temperature, carried by the **main** light only | same | `fan-ceiling.js:29-52` |

`fanSpeedSteps` default is 12 (`device-capabilities.js:270-273`); H1310/R1310 are 6, H1370 is 12.

#### Write frames

| Function | Hex / mechanism | Source |
|---|---|---|
| Fan on (preferred) | `cmd: openApi`, `fanToggle`, `devices.capabilities.toggle`, value 1/0 | `fan-ceiling.js:242-250` |
| Fan on (fallback) | `33 31 01 <speed>` — keeps the cached speed (default 1) | `fan-ceiling.js:251-263` |
| Fan off (fallback) | `33 31 00 <speed>` | same |
| Speed 1-6/12 | `33 31 01 <01-0c>` via `cmd: ptReal` (e.g. `MzEBAQ…AAI=`, `MzEBDAAAA…AAP=`) | `fan-H1370.js:200-204`; table §3.4 |
| Oscillation | `cmd: openApi`, `fanOscillateToggle`, value 1/0 — **no frame is known to send it** | `fan-ceiling.js:322-348` |
| Direction | `cmd: openApi`, `reverseAirflowToggle`, 1 = reverse | `fan-ceiling.js:285-311` |
| Light on/off | `cmd: openApi`, `mainLightToggle` / `backgroundLightToggle` | `fan-ceiling.js:550-573` |
| Light brightness | `cmd: brightness` (AWS `brightness`, 0-100 or 0-254 per model) | `fan-ceiling.js:575-604` |
| Light colour | `cmd: color` (AWS `colorwc` by default) | `fan-ceiling.js:606-628` |
| Light colour temp | `cmd: colorTem` (AWS `colorwc` with kelvin) | `fan-ceiling.js:630-650` |

The base class's `33 36 01 01` / `33 36 00 00` power frames are **light frames** and are only kept for a
device that cannot reach the OpenAPI switches; every mapped model overrides `internalStateUpdate`
(`fan-H1370.js:149-183`, `fan-ceiling.js:224-234`).

#### Report frames

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 31 <run> <speed> <dir> … <osc>` | fan | byte 3 = running (01), byte 4 = speed 1..steps, byte 5 = direction (01 up / 00 down), byte 8 = oscillation (01) | `fan-ceiling.js:127-136`, `433-459`, `467-494`; `fan-H1370.js:384-395` |
| `aa 36 <main> <bg>` | two lights | each byte 01 = lit; normalised to mask bits 0x40 / 0x20 | `fan-ceiling.js:99-119` |
| `aa 42 <mask>` | light mask | 0x40 main, 0x20 background, 0x80 either lit | `fan-ceiling.js:54-77` |
| `aa 31` with byte 3 = 00/01 | running | used instead of `aa 36` for fan power | `fan-ceiling.js:375-390` |

Mask/pair equivalence from the source's 69 captured statuses (`fan-ceiling.js:54-72`):

| `aa 36` | `aa 42` | Lit |
|---|---|---|
| `01 01` | `e0` | both |
| `01 00` | `c0` | main only |
| `00 01` | `a0` | background only |
| `00 00` | `00` | neither |

Captured base64 examples (from the tests, checksum-verified):

| Frame | Base64 |
|---|---|
| `aa 42 00` | `qkIAAAAAAAAAAAAAAAAAAAAAAOg=` |
| `aa 42 c0` | `qkLAAAAAAAAAAAAAAAAAAAAAACg=` |
| `aa 42 a0` | `qkKgAAAAAAAAAAAAAAAAAAAAAEg=` |
| `aa 36 00 00` | `qjYAAAAAAAAAAAAAAAAAAAAAAJw=` |
| `aa 36 01 01` | `qjYBAQAAAAAAAAAAAAAAAAAAAJw=` |
| `aa 31 00 01 00` (stopped, last speed 1) | `qjEAAQAAAAAAAAAAAAAAAAAAAJo=` |
| `aa 31 01 06` | `qjEBBgAAAAAAAAAAAAAAAAAAAJw=` |
| `aa 31 01 0c` | `qjEBDAAAAAAAAAAAAAAAAAAAAJY=` |
| `aa 31 01 04 00 00 00 01` (swinging) | `qjEBBAAAAAEAAAAAAAAAAAAAAJ8=` |

#### Quirks

- `aa 36` was historically read as **fan power** on the H1370; that was wrong and is why every model now runs
  the subclass (`fan-H1370.js:26-33`, `fan-ceiling.js:13-28`).
- The inherited single light is removed when two named lights exist; the background light has its brightness,
  hue, saturation and colour temperature characteristics stripped because the fan has only one of each
  (`fan-ceiling.js:203-221`, `508-525`).
- HomeKit writes brightness 0 when a bulb is switched off. The brightness command is device-wide, so the
  handler turns **that light** off instead of obeying 0 — otherwise switching one light off dimmed both
  (`fan-ceiling.js:583-590`, `29-38`).
- Oscillation has no known write frame; it is OpenAPI-only and is gated on `useOpenApiControl`
  (`fan-ceiling.js:313-321`).
- Direction mapping "reverse" → `value 1` is arbitrary (Govee does not document which way it spins);
  the source says to swap it if an owner reports it backwards (`fan-ceiling.js:277-284`).
- The light is colour-temperature only in practice: 2700-6500 K, mired 154-370 (`fan-H1370.js:127-138`,
  `347-354`).

### 3.4 Fan speed frames, all models

`33 05 01 <n>` (tower fans; H7100 stops at 8, H7105/H7107 at 12):

| n | Hex (full packet) | Base64 |
|---|---|---|
| 1 | `33 05 01 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 36` | `MwUBAQAAAAAAAAAAAAAAAAAAADY=` |
| 2 | `33 05 01 02 … 35` | `MwUBAgAAAAAAAAAAAAAAAAAAADU=` |
| 3 | `33 05 01 03 … 34` | `MwUBAwAAAAAAAAAAAAAAAAAAADQ=` |
| 4 | `33 05 01 04 … 33` | `MwUBBAAAAAAAAAAAAAAAAAAAADM=` |
| 5 | `33 05 01 05 … 32` | `MwUBBQAAAAAAAAAAAAAAAAAAADI=` |
| 6 | `33 05 01 06 … 31` | `MwUBBgAAAAAAAAAAAAAAAAAAADE=` |
| 7 | `33 05 01 07 … 30` | `MwUBBwAAAAAAAAAAAAAAAAAAADA=` |
| 8 | `33 05 01 08 … 3f` | `MwUBCAAAAAAAAAAAAAAAAAAAAD8=` |
| 9 | `33 05 01 09 … 3e` | `MwUBCQAAAAAAAAAAAAAAAAAAAD4=` |
| 10 | `33 05 01 0a … 3d` | `MwUBCgAAAAAAAAAAAAAAAAAAAD0=` |
| 11 | `33 05 01 0b … 3c` | `MwUBCwAAAAAAAAAAAAAAAAAAADw=` |
| 12 | `33 05 01 0c … 3b` | `MwUBDAAAAAAAAAAAAAAAAAAAADs=` |

Auto frames: H7100 `33 05 00 03` = `MwUAAwAAAAAAAAAAAAAAAAAAADU=`; H7105/H7107 `33 05 00 02` =
`MwUAAgAAAAAAAAAAAAAAAAAAADQ=`.

`33 31 01 <n>` (ceiling fans):

| n | Full hex | Base64 |
|---|---|---|
| 1 | `33 31 01 01 … 02` | `MzEBAQAAAAAAAAAAAAAAAAAAAAI=` |
| 2 | `33 31 01 02 … 01` | `MzEBAgAAAAAAAAAAAAAAAAAAAAE=` |
| 3 | `33 31 01 03 … 00` | `MzEBAwAAAAAAAAAAAAAAAAAAAAA=` |
| 4 | `33 31 01 04 … 07` | `MzEBBAAAAAAAAAAAAAAAAAAAAAc=` |
| 5 | `33 31 01 05 … 06` | `MzEBBQAAAAAAAAAAAAAAAAAAAAY=` |
| 6 | `33 31 01 06 … 05` | `MzEBBgAAAAAAAAAAAAAAAAAAAAU=` |
| 7 | `33 31 01 07 … 04` | `MzEBBwAAAAAAAAAAAAAAAAAAAAQ=` |
| 8 | `33 31 01 08 … 0b` | `MzEBCAAAAAAAAAAAAAAAAAAAAAs=` |
| 9 | `33 31 01 09 … 0a` | `MzEBCQAAAAAAAAAAAAAAAAAAAAo=` |
| 10 | `33 31 01 0a … 09` | `MzEBCgAAAAAAAAAAAAAAAAAAAAk=` |
| 11 | `33 31 01 0b … 08` | `MzEBCwAAAAAAAAAAAAAAAAAAAAg=` |
| 12 | `33 31 01 0c … 0f` | `MzEBDAAAAAAAAAAAAAAAAAAAAA8=` |

The byte after the speed differs because the checksum is XOR over all 19 bytes; it is not a second data byte.

---

## 4. Heaters

### 4.1 Heater1 — H7130 / H713A / H713C / H7137 / H713E

Two handlers share the wire protocol. `heater1a.js` is used when the model does **not** report ambient
temperature; it exposes only a Fanv2 tile. `heater1b.js` is used when it does; it exposes a HeaterCooler plus a
plain Fan.

#### Capabilities

| Capability | 1A (no ambient temp) | 1B (ambient temp) | Source |
|---|---|---|---|
| Power | Fanv2 `Active` | HeaterCooler `Active` | `heater1a.js:131-160`, `heater1b.js:206-241` |
| Speed | `RotationSpeed`, valid `[0,33,66,99]`, minStep 33 | fan `RotationSpeed`, same | `heater1a.js:78-86`, `heater1b.js:189-197` |
| Presets | low / medium / high | low / medium / high + auto/heat thermostat mode | `heater1a.js:46-50`, `heater1b.js:139-150` |
| Oscillation | `SwingMode` if `features.swing` | same | `heater1a.js:100-110` |
| Child lock | `LockPhysicalControls` if `features.lock` | same | `heater1a.js:112-122` |
| Current temp | not shown (only used to learn whether the model has a sensor) | `CurrentTemperature` | `heater1a.js:299-313`, `heater1b.js:501-519` |
| Target temp | no | `HeatingThresholdTemperature`, 5-30 °C, step 1 | `heater1b.js:154-163` |
| Display / timer | no | read-but-ignored (`aa 16`, `aa 11`) | `heater1b.js:686-691` |

Feature resolution: family `heater1` defaults `{ swing: true, lock: true, light: false }`
(`capabilities.js:35`). Overrides: H7137 and H713E have **no swing and no lock**
(`capabilities.js:62-66`); H713A, H713B, H713C and H7135 are recorded as probably lacking swing but the
control is still offered (`capabilities.js:86-91`).

#### Write frames (`cmd: ptReal`)

| Function | Hex template | Exact literals | Source |
|---|---|---|---|
| On | `33 01 01` | `MwEBAAAAAAAAAAAAAAAAAAAAADM=` | `heater1a.js:142-146`, `heater1b.js:217-221` |
| Off | `33 01 00` | `MwEAAAAAAAAAAAAAAAAAAAAAADI=` | same |
| Low (33 %) | `33 05 01` | `MwUBAAAAAAAAAAAAAAAAAAAAADc=` | `heater1a.js:41`, `heater1b.js:40` |
| Medium (66 %) | `33 05 02` | `MwUCAAAAAAAAAAAAAAAAAAAAADQ=` | same |
| High (99 %) | `33 05 03` | `MwUDAAAAAAAAAAAAAAAAAAAAADU=` | same |
| Swing on | `33 18 01` | `MxgBAAAAAAAAAAAAAAAAAAAAACo=` | `heater1a.js:178`, `heater1b.js:335` |
| Swing off | `33 18 00` | `MxgAAAAAAAAAAAAAAAAAAAAAACs=` | same |
| Lock on | `33 10 01` | `MxABAAAAAAAAAAAAAAAAAAAAACI=` | `heater1a.js:221`, `heater1b.js:378` |
| Lock off | `33 10 00` | `MxAAAAAAAAAAAAAAAAAAAAAAACM=` | same |
| Target temp, heat | `33 1a 00 00 <tHI> <tLO>` | e.g. 20 °C = `33 1a 00 00 9a 90 … 23` = `MxoAAJqQAAAAAAAAAAAAAAAAACM=` | `heater1b.js:80-107` |
| Target temp, auto | `33 1a 01 00 <tHI> <tLO>` | e.g. 20 °C = `33 1a 01 00 9a 90 … 22` = `MxoBAJqQAAAAAAAAAAAAAAAAACI=` | `heater1b.js:51-78` |

OpenAPI mirrors:

- speed: `workMode` `{ workMode: 1, modeValue: 33|66|99 }` (`heater1a.js:265-275`, `heater1b.js:460-471`)
- swing: `oscillationToggle`, lock: `lockToggle` (`heater1a.js:176-186`, `219-229`)
- target: `targetTemperature`, `devices.capabilities.temperature_setting`, `{ temperature, unit: 'Celsius' }`
  (`heater1b.js:294-305`)

Changing the thermostat mode re-sends the **temperature frame** at the cached target, with byte 2 selecting
heat (`00`) or auto (`01`) — there is no mode-only frame (`heater1b.js:243-280`). The temperature range is
5-30 °C; each value has a hard-coded literal (`heater1b.js:51-107`).

Temperature encoding: bytes 5-6 are a 16-bit big-endian value — bit 15 is the sign/positive flag and the low
15 bits are hundredths of a degree Fahrenheit:

```
value = 0x8000 | (floor(°C × 9/5 + 32) × 100)
```

(`heater1b.js:51-107`; verified against the table in §4.3.)

#### Report frames

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 18 <0/1>` | oscillation | byte 3 (the sub-command byte itself) | `heater1a.js:366-383` |
| `aa 10 <0/1>` | child lock | byte 3 | `heater1a.js:384-401` |
| `aa 05 <1/2/3>` | fan speed | byte 3: 1 = 33 %, 2 = 66 %, 3 = 99 % | `heater1a.js:402-435` |
| `aa 1a <0/1>` | thermostat mode | byte 3: 01 = auto, 00 = heat | `heater1b.js:672-685` |
| `aa 11 00/01` | timer | known-ignored | `heater1b.js:686-691` |
| `aa 13 00` | schedule | known-ignored | same |
| `aa 16 00/01` | display or DND (the two handlers' comments disagree) | known-ignored | same |

Current and target temperature do **not** come from an `aa` frame: they come from the AWS status fields
`state.sta.curTem` and `state.sta.setTem`, both hundredths of a degree Fahrenheit, converted with
`farToCen` (whole °C) (`heater1b.js:501-529`; `response-parser.js:209-219`). `farToCen` rounds to an integer
(`functions.js:15`), so heater temperatures are whole °C. A "current temperature" above 100 °C is treated as
"this model does not really report ambient temperature" and remembered (`heater1b.js:505-512`; 1A learns the
opposite at `heater1a.js:300-312`).

#### Quirks

- 1A has no climate tile at all: it deletes any HeaterCooler and builds Fanv2 (`heater1a.js:52-68`).
- 1A/1B both send `33 01 01` for power, but the 1B fan tile tracks the heater power and cannot be turned on
  independently: turning the fan "on" while the heater is off is undone after 3 s; turning it "off" is undone
  after 2 s (`heater1b.js:405-442`).
- 1B sets `TargetHeaterCoolerState` valid values `[0, 1]` only: 0 = auto, 1 = heat (`heater1b.js:139-150`).
- The 1A fallback keeps the swing/lock send methods in the class even though the characteristics are only wired
  up when `features.swing` / `features.lock` allow it (`heater1a.js:100-122`, `162-246`).
- OpenAPI `workMode` reports map `{1:33, 2:66, 3:99}` back to the HK percentages (`heater1a.js:315-327`,
  `heater1b.js:531-543`): OpenAPI `modeValue` is 1/2/3, while the AWS frames carry 1/2/3 in the speed byte
  (byte 2 of `33 05 01/02/03`).

### 4.2 Heater2 — H7131 / H7132 / H7133 / H7134 / H7135 / H713B

Handler: `lib/device/heater2.js`. Builds HeaterCooler + Fan + Lightbulb. H713B is on this handler because it
last worked here in v10; on heater1 its AWS commands are acknowledged and ignored (`constants.js:764-773`).

#### Capabilities

| Capability | Value | Source |
|---|---|---|
| Power | HeaterCooler `Active` | `heater2.js:250-284` |
| Modes | auto (thermostat), fan-only, low, medium, high | `heater2.js:18-64` |
| Fan speeds | `[0, 25, 50, 75, 100]`, minStep 25 | `heater2.js:201-209` |
| Target temp | 5-30 °C, step 1 | `heater2.js:166-175` |
| Current temp | `CurrentTemperature` | `heater2.js:693-701` |
| Oscillation | `SwingMode` | `heater2.js:177-183` |
| Child lock | `LockPhysicalControls` | `heater2.js:185-191` |
| Night light | on/off, brightness, RGB | `heater2.js:142-243`, `553-681` |
| Timer / display | read-but-ignored (`aa 11`, `aa 16`) | `heater2.js:934-940` |

#### Write frames (all via `cmd: multiSync`, even the `33`-prefixed ones)

| Function | Hex template | Exact literals | Source |
|---|---|---|---|
| Power on / off | `33 01 01` / `33 01 00` (command `stateHeat` → AWS `multiSync`) | `MwEB…ADM=` / `MwE…ADI=` | `heater2.js:262-265`, `command-builder.js:125-140` |
| Fan-only (25 %) | `3a 05 09` | `OgUJAAAAAAAAAAAAAAAAAAAAADY=` | `heater2.js:52` |
| Low (50 %) | `3a 05 01 01` | `OgUBAQAAAAAAAAAAAAAAAAAAAD8=` | `heater2.js:53` |
| Medium (75 %) | `3a 05 01 02` | `OgUBAgAAAAAAAAAAAAAAAAAAADw=` | `heater2.js:54` |
| High (100 %) | `3a 05 01 03` | `OgUBAwAAAAAAAAAAAAAAAAAAAD0=` | `heater2.js:55` |
| Target temp, already auto | `33 05 03 01 <tHI> <tLO>` | 20 °C: `33 05 03 01 9a 90 … 3e` = `MwUDAZqQAAAAAAAAAAAAAAAAAD4=` | `heater2.js:66-93` |
| Target temp, entering auto | `3a 05 03 01 <tHI> <tLO>` | 20 °C: `3a 05 03 01 9a 90 … 37` = `OgUDAZqQAAAAAAAAAAAAAAAAADc=` | `heater2.js:95-122` |
| Swing on / off | `33 1f 01 01` / `33 1f 01 00` | `Mx8BAQ…ACw=` / `Mx8B…AC0=` | `heater2.js:396-400` |
| Lock on / off | `33 1f 02 01` / `33 1f 02 00` | `Mx8CAQ…AC8=` / `Mx8C…AC4=` | `heater2.js:443-447` |
| Light on / off | `3a 1b 01 01 <0/1>` | e.g. on: `3a 1b 01 01 01 … 20` = `OhsBAQEAAAAAAAAAAAAAAAAAACA=` | `heater2.js:562-575` |
| Light brightness | `3a 1b 01 02 <0-100>` | e.g. 50: `OhsBAjIAAAAAAAAAAAAAAAAAABA=` | `heater2.js:604-611` |
| Light colour | `3a 1b 05 0d RR GG BB` | e.g. red: `OhsFDf8AAAAAAAAAAAAAAAAAANY=` | `heater2.js:660-666` |

Setting a target temperature always sets the heater to **auto** (`heater2.js:344-380`); mode auto likewise
uses the "turn" variant (`heater2.js:291-300`). Selecting a speed sets mode to heat and turns the heater Active
(`heater2.js:521-551`). Turning the fan off just switches the tile to auto; it sends no fan-off frame
(`heater2.js:476-519`).

OpenAPI mirrors: `workMode` (`{workMode: 5, modeValue: target}` for auto, `{workMode: 1, modeValue: speed}`
for heat), `targetTemperature`, `oscillationToggle`, `lockToggle` (`heater2.js:302-320`, `356-367`,
`396-410`, `443-457`). The API-side speed map is `{1:33, 2:66, 3:99}` even though this model's own values are
25/50/75/100 — a legacy inconsistency (`heater2.js:734-743`).

#### Report frames

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 1b 01 <on> <bright>` | light on/off + brightness | byte 4 state, byte 5 0-100 | `heater2.js:794-810` |
| `aa 1b 05 0d RR GG BB` | light colour | bytes 5-7 | `heater2.js:811-832` |
| `aa 1f <x> <swing> <lock>` | swing **and** lock in one frame | byte 3 swing, byte 4 lock | `heater2.js:833-859` |
| `aa 05 09` | fan-only mode | sets mode fan-only, 25 % | `heater2.js:860-873` |
| `aa 05 01 <1/2/3>` | speed | 1 → 50 %, 2 → 75 %, 3 → 100 % | `heater2.js:874-920` |
| `aa 05 03` | auto / thermostat mode | clears fan, speed 0, mode auto | `heater2.js:921-933` |
| `aa 1a 00` | target temperature, thermostat off | ignored | `heater2.js:934-940` |
| `aa 11 00/01`, `aa 16 00/01` | timer, display/DND | ignored | same |

Note the send/report asymmetry for the lock: the write uses sub-command `02` (`33 1f 02 …`) while the report
only ever has `aa 1f 00`/`01` with the lock in byte 4. The source does not explain it; treat `33 1f 02` as
confirmed-by-use, not as decoded.

#### Quirks

- The light status frame also carries brightness while the light is off; brightness is updated regardless
  (`heater2.js:803-808`).
- A reported `setTemperature` is taken as proof of auto mode and clears the fan/speed caches
  (`heater2.js:704-716`).
- `aa 05` is heavily overloaded even inside this one file: `0509` fan-only, `0501 <n>` speed, `0503` auto.
- H7135 and H713B are recorded as probably lacking a light and/or swing, but those controls are still offered
  (`capabilities.js:86-91`).

### 4.3 Target-temperature byte table (heater1 and heater2)

All four tables (heater1 auto, heater1 heat, heater2 auto, heater2 turn) use the same two bytes; only the frame
prefix, the mode byte and therefore the checksum differ.

| °C | °F (floored) | value | byte HI | byte LO |
|---|---|---|---|---|
| 5 | 41 | 0x9004 | `90` | `04` |
| 6 | 42 | 0x9068 | `90` | `68` |
| 7 | 44 | 0x9130 | `91` | `30` |
| 8 | 46 | 0x91f8 | `91` | `f8` |
| 9 | 48 | 0x92c0 | `92` | `c0` |
| 10 | 50 | 0x9388 | `93` | `88` |
| 11 | 51 | 0x93ec | `93` | `ec` |
| 12 | 53 | 0x94b4 | `94` | `b4` |
| 13 | 55 | 0x957c | `95` | `7c` |
| 14 | 57 | 0x9644 | `96` | `44` |
| 15 | 59 | 0x970c | `97` | `0c` |
| 16 | 60 | 0x9770 | `97` | `70` |
| 17 | 62 | 0x9838 | `98` | `38` |
| 18 | 64 | 0x9900 | `99` | `00` |
| 19 | 66 | 0x99c8 | `99` | `c8` |
| 20 | 68 | 0x9a90 | `9a` | `90` |
| 21 | 69 | 0x9af4 | `9a` | `f4` |
| 22 | 71 | 0x9bbc | `9b` | `bc` |
| 23 | 73 | 0x9c84 | `9c` | `84` |
| 24 | 75 | 0x9d4c | `9d` | `4c` |
| 25 | 77 | 0x9e14 | `9e` | `14` |
| 26 | 78 | 0x9e78 | `9e` | `78` |
| 27 | 80 | 0x9f40 | `9f` | `40` |
| 28 | 82 | 0xa008 | `a0` | `08` |
| 29 | 84 | 0xa0d0 | `a0` | `d0` |
| 30 | 86 | 0xa198 | `a1` | `98` |

The source literally contains all 26 base64 literals for each table: `heater1b.js:51-78` (auto),
`heater1b.js:80-107` (heat), `heater2.js:66-93` (auto), `heater2.js:95-122` (turn). Examples:

| Meaning | Base64 |
|---|---|
| heater1 auto 5 °C | `MxoBAJAEAAAAAAAAAAAAAAAAALw=` |
| heater1 heat 5 °C | `MxoAAJAEAAAAAAAAAAAAAAAAAL0=` |
| heater1 auto 6 °C | `MxoBAJBoAAAAAAAAAAAAAAAAANA=` |
| heater1 heat 6 °C | `MxoAAJBoAAAAAAAAAAAAAAAAANE=` |
| heater2 auto 5 °C | `MwUDAZAEAAAAAAAAAAAAAAAAAKA=` |
| heater2 turn 5 °C | `OgUDAZAEAAAAAAAAAAAAAAAAAKk=` |
| heater2 auto 30 °C | `MwUDAaGYAAAAAAAAAAAAAAAAAA0=` |
| heater2 turn 30 °C | `OgUDAaGYAAAAAAAAAAAAAAAAAAQ=` |

### 4.4 heater-single / cooler-single (smart plug shown as heater/cooler)

Handlers: `lib/device/heater-single.js`, `lib/device/cooler-single.js`. These do not speak an appliance
protocol at all: they wrap a single smart plug or switch (`showAs: 'heater'` or `'cooler'` plus a
`temperatureSource`, `dispatch.js:125-134`) in a HeaterCooler service and drive the plug on/off from an
externally supplied temperature.

| Aspect | Heater-single | Cooler-single |
|---|---|---|
| Target characteristic | `HeatingThresholdTemperature`, step 0.5 | `CoolingThresholdTemperature`, step 0.5 |
| Thermostat mode | locked to Auto, validValues `[0]` | same |
| Current temp | storage key `${temperatureSource}_temp`, polled every 120 s after 5 s | same |
| Active on | if `cacheTemp < cacheTarget` | if `cacheTemp > cacheTarget` |
| Active off | if `cacheTemp >= cacheTarget` | if `cacheTemp <= cacheTarget` |
| Send | `cmd: stateOutlet`, `'on'`/`'off'` | same |
| OpenAPI | `powerSwitch`, on_off, 1/0 | same |
| Hysteresis | none; the comparison is re-evaluated on every temperature poll | same |

Source: `heater-single.js:101-165`, `167-227`, `282-300`; `cooler-single.js:101-165`, `167-227`,
`282-300`. The plug's AWS power values are 1/0, or 17/16 for H5080/H5083 (`command-builder.js:96-109`).
`externalUpdate()` is deliberately empty — all status comes from the temperature source
(`heater-single.js:302`).

The handler also removes stale AirPurifier/Lightbulb/Outlet/Switch/Valve services and re-creates the
HeaterCooler if the previous `cacheType` was the other one (`heater-single.js:11-41`).

---

## 5. Ice makers

Handler: `lib/device/ice-maker-H7172.js` for H7172, H717D, H8120, H8121, H8122. H8102 and H8131 fall back to
`deviceIceMakerBasic` (power only).

### 5.1 Capabilities

| Capability | Behaviour | Source |
|---|---|---|
| Power | Fanv2 `Active`; ice making on/off | `ice-maker-H7172.js:92-101` |
| Ice size | Fanv2 `RotationSpeed`, maxValue **3**, minStep 1 (1 small, 2 medium, 3 large) | `:106-123` |
| No size option | H8120 has `iceSizes: false`; the characteristic is removed and power uses `33 01` | `:106-127`, `:143-157` |
| Night light | only if OpenAPI says `nightlightToggle` | `:44-89` |
| Brightness | only if OpenAPI says `brightness` | `:54-59` |
| Colour | only if OpenAPI says `colorRgb` | `:60-85` |
| Basket full / water empty | **not implemented** — no frame or capability exists in this project | — |
| Timer / display | not implemented | — |

`RotationSpeed` defaults to 2 (medium) when unset, and is forced to match the cache so the tile is not
`Active=1` with speed 0 (`ice-maker-H7172.js:116-123`).

### 5.2 Write frames (`cmd: ptReal`, except the H8120 colour which is `multiSync`)

| Function | Hex template | Base64 | Source |
|---|---|---|---|
| Small (older models) | `33 05 03` | `MwUDAAAAAAAAAAAAAAAAAAAAADU=` | `:20-24`; test `ice-maker.test.js:23-29` |
| Medium | `33 05 02` | `MwUCAAAAAAAAAAAAAAAAAAAAADQ=` | same |
| Large (older models) | `33 05 01` | `MwUBAAAAAAAAAAAAAAAAAAAAADc=` | same |
| Small (H8121/H8122) | `33 05 01` | `MwUBAAAAAAAAAAAAAAAAAAAAADc=` | `device-capabilities.js:128-129`; test `:31-37` |
| Medium | `33 05 02` | `MwUCAAAAAAAAAAAAAAAAAAAAADQ=` | same |
| Large (H8121/H8122) | `33 05 03` | `MwUDAAAAAAAAAAAAAAAAAAAAADU=` | same |
| Power off (non-H8120) | `33 19 00` | `MxkAAAAAAAAAAAAAAAAAAAAAACo=` | `:173-176` |
| Power on (H8120) | `33 01 01` | `MwEBAAAAAAAAAAAAAAAAAAAAADM=` | `:150-157` |
| Power off (H8120) | `33 01 00` | `MwEAAAAAAAAAAAAAAAAAAAAAADI=` | same |
| Night-light colour (H8120) | `3a b6 15 fc 01 RR GG BB` | e.g. red: `OrYV/AH/AAAAAAAAAAAAAAAAAJs=` | `:310-318` |

For the H8120 colour frame, `fc` is "commit"; the capture notes that `fe` previews without saving
(`ice-maker-H7172.js:311-314`).

Ice size order is per model, from `caps.iceSizeAscending` (default **false**):

| Models | ascending | small | medium | large |
|---|---|---|---|---|
| H7172, H717D, H8120 (any model on this handler that is not H8121/H8122) | false | `03` | `02` | `01` |
| H8121, H8122 | true | `01` | `02` | `03` |

`device-capabilities.js:125-129`, `266`; pinned by `ice-maker.test.js:22-56`. H8120 computes the codes but
does not expose the control.

On (non-H8120) sends the **size frame** for the cached size, not a separate power frame
(`ice-maker-H7172.js:158-170`). Off sends `33 19 00` (`:171-184`).

OpenAPI mirrors:

- power/size on: `workMode { workMode: cacheSize, modeValue: 0 }` (`:163-169`)
- size change: `workMode { workMode: value, modeValue: 0 }` (`:219-229`)
- off: `workMode { workMode: 0, modeValue: 0 }` (`:176-183`)
- light on/off: `nightlightToggle`, toggle 1/0 (`:249-256`)
- brightness: `brightness`, range 0-100 (`:271-278`)
- colour (non-H8120): `colorRgb`, `(r<<16)+(g<<8)+b` (`:321-328`)

**H8120 quirk**: `icePowerOnOff: true` (`device-capabilities.js:131-137`) switches it to the universal
`33 01 <0/1>` power frame. The #1250 capture showed `33 01 00` in both directions, which first looked like a
toggle, but the owner's live test proved it is **absolute OFF** (`ice-maker-H7172.js:143-157`). It has no ice
size control in the app and its night-light colour must go over `multiSync` because the OpenAPI `colorRgb`
write is accepted but does nothing (`device-capabilities.js:131-137`, `ice-maker-H7172.js:310-318`).

### 5.3 Report frames

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 19 <0/1>` | power | byte 3 | `ice-maker-H7172.js:376-389` |
| `aa 1b 01 <on> <bright>` | night light | byte 4 state, byte 5 1-100; only read if byte 3 == `01` | `:390-415` |
| `aa 05 …` | ice size | **deliberately not decoded** — shape only, to stop it being logged as a new scene | `:416-423` |

The night-light brightness is only written to the light if the device advertised `brightness`
(`ice-maker-H7172.js:407-412`). The `aa 05` comment explains why it is not decoded: the size byte order
differs per model while OpenAPI sends `workMode` un-inverted, and which is authoritative is unresolved
(#1329). Do not "fix" this by assuming an order.

Power state is also taken from OpenAPI `workMode` 1-3 → on (and size), 0 → off (`:337-361`). Generic
`state.onOff` is ignored.

---

## 6. Kettles

Handler: `lib/device/kettle.js` for all five SKUs. There is **no target-temperature write command**: the
kettle's presets are the controls, and the target is chosen on the device/app.

### 6.1 Capabilities

| Capability | Value | Source |
|---|---|---|
| Preset switches | Green Tea, Oolong Tea, Coffee, Black Tea/Boil | `kettle.js:115-169` |
| Optional presets | Custom Mode 1 / 2 (config `showCustomMode1/2`) | `:171-197` |
| Water temperature | `TemperatureSensor`, created on first reading | `:199-207`, `329-346` |
| On-base sensor | `ContactSensor` "On Base" | `:209-215` |
| Heating state | `ContactSensor` "Heating", created on first `aa 19` | `:348-385` |
| Keep warm | **read-only log line**, no control | `:408-434` |
| Target temp | not settable | — |
| Timer / schedule | known-ignored (`aa 23`) | `:589-593` |

Config hides each preset (`hideModeGreenTea`, etc.) and shows the two custom modes
(`constants.js:144-154`).

### 6.2 Write frames (`cmd: ptReal`)

Each switch press sends **two** frames, 1 s apart: the mode, then an "enable/boil" frame.

| Preset | Mode frame | Base64 | Enable frame listed in the header comment |
|---|---|---|---|
| Green Tea | `33 05 00 02` | `MwUAAgAAAAAAAAAAAAAAAAAAADQ=` | `33 01 01 02` (`MwEBAg…ADk=`) |
| Oolong Tea | `33 05 00 03` | `MwUAAwAAAAAAAAAAAAAAAAAAADU=` | `33 01 01 03` (`MwEBAw…ADg=`) |
| Coffee | `33 05 00 04` | `MwUABAAAAAAAAAAAAAAAAAAAADI=` | `33 01 01 04` (`MwEBBAAAAAAAAAAAAAAAAAAAADc=`) |
| Black Tea / Boil | `33 05 00 05` | `MwUABQAAAAAAAAAAAAAAAAAAADM=` | `33 01 01 05` (`MwEBBQ…ADY=`) |
| Custom Mode 1 | `33 05 00 01 01` | `MwUAAQEAAAAAAAAAAAAAAAAAADY=` | — |
| Custom Mode 2 | `33 05 00 01 02` | `MwUAAQIAAAAAAAAAAAAAAAAAADU=` | — |

Source: `kettle.js:13-27` (comment) and `:106-113` (code). ⚠️ **The code does not send the per-mode enable
frames from the comment.** After 1 s it sends the plain universal power frame
`33 01 01` = `MwEBAAAAAAAAAAAAAAAAAAAAADM=` (`kettle.js:294-307`), for every preset. The comment is the
older observation; the implementation is what runs. The switch resets itself to off after 3 s
(`kettle.js:312-314`).

OpenAPI workMode: green tea 2, oolong 3, coffee 4, black tea 5, both custom modes 1; first
`{ workMode: mode, modeValue: 0 }`, then `{ workMode: mode, modeValue: 1 }`
(`kettle.js:270-307`).

### 6.3 Report frames

| Frame | Meaning | Decode | Source |
|---|---|---|---|
| `aa 05 <slot> <°F>` | preset temperatures, sent on startup | slot 1 = current target, 2-5 = memory presets; byte 4 is whole °F, accepted only 90-212 | `kettle.js:455-513` |
| `aa 05 00 <slot>` | which control the target came from | 1 = custom slider, 2-5 = preset 1-4 | `kettle.js:516-564` |
| `aa 10 01 <2 bytes>` | current water temperature | bytes 4-5, hundredths °F; accepted only 32-230 °F | `kettle.js:46-56`, `565-568` |
| `aa 17 00 <00>` | on base | byte 4 == `00` = yes | `kettle.js:569-584` |
| `aa 19 <00/01/02/04>` | heating state | 00 idle, 01 heating, 02 keeping warm, 04 reached target | `kettle.js:90-95`, `594-604` |
| `aa 22 01 <m1> <m2>` | keep warm duration | two equal 16-bit minute counts, 1..1440; unequal → unknown | `kettle.js:387-434`, `585-588` |
| `aa 22 00` | keep warm off | ignored | `:589` |
| `aa 23 00/01` | scheduled start | ignored | `:590-593` |
| `aa 17 01`, `aa 1f 06`, `aa 1f 08` | other startup frames | debug only | `:605-613` |

Captured startup examples (from the tests, all checksum-verified):

| Frame | Base64 |
|---|---|
| `aa 05 01 d4` (target 212 °F) | `qgUB1AAAAAAAAAAAAAAAAAAAAHo=` |
| `aa 05 02 d4` (preset 1 212 °F) | `qgUC1AAAAAAAAAAAAAAAAAAAAHk=` |
| `aa 05 03 b4` (preset 2 180 °F) | `qgUDtAAAAAAAAAAAAAAAAAAAABg=` |
| `aa 05 04 c3` (preset 3 195 °F) | `qgUEwwAAAAAAAAAAAAAAAAAAAGg=` |
| `aa 05 05 cd` (preset 4 205 °F) | `qgUFzQAAAAAAAAAAAAAAAAAAAGc=` |
| `aa 05 00 02` (target from M1) | `qgUAAgAAAAAAAAAAAAAAAAAAAK0=` |
| `aa 05 00 01` (target from slider) | `qgUAAQAAAAAAAAAAAAAAAAAAAK4=` |
| `aa 10 01 00 00` (not a temperature) | `qhABAAAAAAAAAAAAAAAAAAAAALs=` |
| `aa 19 00` (idle) | `qhkAAAAAAAAAAAAAAAAAAAAAALM=` |
| `aa 1f 08 01` | `qh8IAQAAAAAAAAAAAAAAAAAAALw=` |
| `aa 1f 06 01` | `qh8GAQAAAAAAAAAAAAAAAAAAALI=` |
| `aa 17 01 00 80` | `qhcBAIAAAAAAAAAAAAAAAAAAADw=` |

Keep-warm decode: with 2 h configured the frame is `aa 22 01 00 78 00 78`; changed to 30 min it becomes
`aa 22 01 00 1e 00 1e` (`kettle.js:387-407`). The second copy has never differed from the first; a mismatch is
reported as unreadable rather than guessed. There is no `aa 22` write command in this handler.

### 6.4 Quirks

- `aa 05` has two meanings selected by the slot byte: `00` = which control the target comes from; non-zero =
  slot temperature. The `aa 05 00` form also collides with the fan/heater/ice uses of `aa 05` (different
  families only).
- The preset **slot order does not match the mode ids**: slots 02-05 arrive in app-list order (black tea,
  green tea, oolong, coffee) while the switch modes are green 02, oolong 03, coffee 04, black 05
  (`kettle.js:466-474`). No attempt is made to name the slots.
- Only the H7171 has been seen sending `aa 10 01`, `aa 19` and `aa 22`; the H7173 sends `aa 05 <x> <0/1>`
  with a non-temperature fourth byte, which is why the 90-212 °F plausibility check exists
  (`kettle.js:46-56`, `479-497`).
- Heating state mapping comes from one instrumented run; `04` and `02` arrive in the same second, so which is
  "reached target" vs "entered keep warm" is inferred from order, not proven (`kettle.js:58-77`).
- The handler logs preset values and keep-warm durations to the normal log once each, then debug
  (`kettle.js:499-511`, `429-433`).

---

## 7. Cross-family `aa` identifier table

The same second byte means different things per family. Dispatch is always by model family first, so this is
only a hazard for a shared decoder.

| Frame | Family | Meaning |
|---|---|---|
| `aa 01 <0/1>` | basic appliances | power (fallback handler only) |
| `aa 05 00 02` / `aa 05 00 03` | tower fans | auto (H7105/H7107 = 02, H7100 = 03) |
| `aa 05 01 <1-12>` | tower fans | speed |
| `aa 05 <1/2/3>` | heater1 | low / medium / high |
| `aa 05 01 <1/2/3>` | heater2 | low / medium / high |
| `aa 05 09` | heater2 | fan-only |
| `aa 05 03` | heater2 | auto / thermostat |
| `aa 05 <slot≠00> <°F>` | kettle | preset temperature |
| `aa 05 00 <slot>` | kettle | target source |
| `aa 05 …` | ice maker | ice size (not decoded) |
| `aa 08 …` | tower fans | sensor attached |
| `aa 10 <flags> <3B>` | H7107 | room temperature |
| `aa 10 <0/1>` | heater1 | child lock |
| `aa 10 01 <2B>` | kettle | water temperature |
| `aa 18 <0/1>` | heater1 | oscillation |
| `aa 19 <0/1>` | ice maker | power |
| `aa 19 <00/01/02/04>` | kettle | heating state |
| `aa 1a <0/1>` | heater1 | heat / auto |
| `aa 1a 00` | heater2 | target temperature, thermostat off (ignored) |
| `aa 1b 01 <on> <bright>` | H7105/H7107, heater2, ice maker | night light |
| `aa 1b 05 0d RGB` | H7105/H7107, heater2 | night-light colour |
| `aa 1d <0/1> <range>` | H7105/H7107 | oscillation + range |
| `aa 1f 01 <0/1>` | H7100 | oscillation |
| `aa 1f <x> <swing> <lock>` | heater2 | oscillation + child lock |
| `aa 22 01 <m1> <m2>` | kettle | keep-warm minutes |
| `aa 31 <run> <speed> <dir> … <osc>` | ceiling fans | fan state |
| `aa 36 <main> <bg>` | ceiling fans | two lights |
| `aa 42 <mask>` | ceiling fans | light mask |
| `aa 11 00/01` | heater1/heater2 | timer (ignored) |
| `aa 13 00` | heater1 | schedule (ignored) |
| `aa 16 00/01` | heater1/heater2 | display or DND (ignored) |
| `aa 17 00 <00>`, `aa 17 01` | kettle | on base / other startup |
| `aa 23 00/01` | kettle | scheduled start (ignored) |

---

## 8. Undecoded / known-ignored

These are explicitly not implemented in the source, so a port must not invent them:

| Item | Where | Status |
|---|---|---|
| Ice-maker basket full / water empty | — | no frame or capability anywhere in the project |
| Ice-maker ice-size report (`aa 05`) | `ice-maker-H7172.js:416-423` | shape only; byte order unresolved (#1329) |
| Ice-maker timer / display | — | no handler |
| H7105/H7107 Sleep / Nature / Custom modes | — | no frames; only auto is a frame |
| H7100 Auto from the slider | `fan-H7100.js:145` | frame exists (`33 05 00 03`) but mapping never selects step 9 |
| Ceiling-fan oscillation **write** | `fan-ceiling.js:313-321` | OpenAPI only; no known frame |
| Ceiling-fan direction **write** | `fan-ceiling.js:285-311` | OpenAPI only |
| Heater1 display/DND / timer / schedule | `heater1b.js:686-691` | frames seen, ignored |
| Heater2 display / timer | `heater2.js:934-940` | frames seen, ignored |
| Kettle keep-warm **control** | `kettle.js:408-434` | duration is read and logged; no write command |
| Kettle scheduled start | `kettle.js:589-593` | ignored |
| Kettle target temperature | — | presets only; no set-temperature frame |
| H713A / H713C / H7135 swing (H7135 also light) | `capabilities.js:86-91` | believed missing, control still offered pending confirmation; H713B is on heater2, which does not consult this table |

---

## 9. Enum / value quick reference

| Family | Value on wire | Meaning |
|---|---|---|
| H7100 fan | `33 05 01 01-08` | speed 1-8 |
| H7100 fan | `33 05 00 03` | auto (reported as 100 %) |
| H7100 OpenAPI | `workMode 1` + `modeValue 1-8` | speed |
| H7100 OpenAPI | `workMode 3` | auto |
| H7105/H7107 fan | `33 05 01 01-0c` | speed 1-12 |
| H7105/H7107 fan | `33 05 00 02` | auto |
| H7105/H7107 OpenAPI | `workMode 2` | auto |
| Ceiling fan | `33 31 01 01-06` / `01-0c` | speed 1-6 (H1310/R1310) / 1-12 (H1370) |
| Ceiling fan | `aa 31` byte 5 `00`/`01` | downward / upward |
| Ceiling fan | `aa 31` byte 8 `00`/`01` | still / swinging |
| Heater1 | `33 05 01/02/03` | low (33 %) / medium (66 %) / high (99 %) |
| Heater1 | `33 1a 00/01 …` | heat / auto thermostat |
| Heater1 OpenAPI | `workMode 1`, `modeValue 33/66/99` | fan speed |
| Heater2 | `3a 05 09` | fan-only (25 %) |
| Heater2 | `3a 05 01 01/02/03` | low (50 %) / medium (75 %) / high (100 %) |
| Heater2 | `33/3a 05 03 01 <t>` | auto (already auto / entering auto) |
| Heater2 OpenAPI | `workMode 5` (or 3) + `modeValue` target | auto thermostat |
| Ice maker | `33 05 01/02/03` | size 1/2/3, order per model |
| Ice maker OpenAPI | `workMode 1/2/3`, `modeValue 0` | size, on |
| Ice maker OpenAPI | `workMode 0` | off |
| Kettle | `33 05 00 01-05` | mode id: 01 custom (5th byte 01/02), 02 green, 03 oolong, 04 coffee, 05 black |
| Kettle | `33 01 01` | enable / boil (sent for every preset) |

Temperature fields:

| Field | Unit | Notes |
|---|---|---|
| `state.sta.curTem` / `setTem` (heaters) | hundredths °F | converted with `farToCen`, rounded to whole °C |
| heater target frame bytes 5-6 | `0x8000 \| floor(°F) × 100` | see §4.3 |
| `aa 10 <flags> <3B>` (H7107) | °F × 10000, bit 23 sign | floor to 0.1 °F |
| `aa 10 01 <2B>` (kettle) | hundredths °F | plausibility 32-230 °F |
| `aa 05 <slot> <°F>` (kettle) | whole °F | plausibility 90-212 °F |
| `aa 22 01 …` (kettle) | whole minutes ×2 | 1-1440 |

---

## 10. Suggested HA entity mapping

HomeKit percentages are **not** always 0-100: heater1 uses 33/66/99, heater2 25/50/75/100, and the ice maker
uses 1-3. A port should expose named presets/selects and keep the raw step as the wire value.

| Family | HA entities | Notes |
|---|---|---|
| H7100 fan | `fan` (on/off, percentage 1-8 → HA %, preset auto read-only) | auto frame exists but is unreachable from HomeKit; a port could expose it |
| H7105/H7107 | `fan` (percentage 1-12, preset auto, swing), `light` (on/off, brightness, RGB), `sensor` temperature (H7107) | fix the raw-step report bug when porting |
| Ceiling fan | `fan` (percentage, direction, swing on H1370), `light` main (brightness + colour temp 2700-6500 K, RGB via `colorwc`), `light` background (on/off) | shared brightness/colour belongs to the main light only |
| Heater1A | `fan` (preset low/medium/high), `switch` swing, `switch` child lock | no climate tile, no temperature |
| Heater1B | `climate` (off/heat/auto, current temp, target 5-30 °C), `fan` (preset low/medium/high), `switch` swing, `switch` child lock | mode changes resend the temperature frame |
| Heater2 | `climate` (off/heat/auto, current temp, target 5-30 °C), `fan` (auto/fan-only/low/medium/high), `light` (on/off, brightness, RGB), `switch` swing, `switch` child lock | auto target uses `33/3a 05 03 01 <t>` |
| Heater-single / cooler-single | `climate` only, with an external temperature entity | power goes through the plug's `turn` command; no appliance frames |
| Ice maker | `switch` (power), `select` (small/medium/large), `light` if the account advertises it | size order is per model; H8120 has no size |
| Kettle | `button` ×4 (+2 custom), `binary_sensor` on-base, `binary_sensor` heating, `sensor` water temperature, `sensor` keep-warm duration (diagnostic) | no target-temperature control |

State decoding can reuse the generic fields (`state.onOff`, `state.brightness`, `state.colorTemInKelvin`,
`state.sta.curTem`, `state.sta.setTem`, `state.workMode`, `state.toggles`) before falling back to
`op.command` frames; that is exactly the order the reference implementation uses (`response-parser.js:96-290`,
then each handler's `externalUpdate`).
