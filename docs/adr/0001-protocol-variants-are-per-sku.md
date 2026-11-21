# Protocol variants are per-SKU, not per-device-kind

Govee devices do not share a consistent opcode scheme: two SKUs of the same kind can use unrelated frames, and one product family can span several wire variants. We assign a family dialect only from evidence — app research, device captures, or a verified handler — and keep a per-SKU override path. Sharing a codec is an optimization for SKUs proven byte-identical, never an assumption from kind, category, or model prefix.

## Consequences

- Reconciliation is bounded to supported SKUs and records the source and confidence of each assignment.
- Golden-frame tests are per SKU; tests must not assert that two devices of the same kind produce the same frame.
- Entity capabilities come from the profile, not from the device's kind.
