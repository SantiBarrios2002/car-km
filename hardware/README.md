# car-km hardware — Rev 2: Waveshare ESP32-S3-Touch-LCD-2.8 + carrier PCB

Status: **design verified against the Waveshare schematic and 2D drawing (6 Oct 2026), nothing ordered**.
Design discussion with diagrams: build-spec doc, tab "Rev 2: Waveshare + carrier PCB". This file is the repo copy.

Sources read: `ESP32-S3-Touch-LCD-2.8.pdf` (schematic), `ESP32-S3-Touch-LCD-2.8_2D.pdf` (drawing),
`esp32-s3-touch-lcd-2_8.stp` (3D). Keep them in `hardware/vendor/` (not redistributed here; download from the Waveshare wiki).

## What the Waveshare module gives us (from the schematic)

| Item | Fact | Consequence |
| --- | --- | --- |
| J8 "12-pin header" | **JST SH 1.0 mm, 12 pins** (`SH1.0-12P`) | Module connects to the carrier with a 12-way SH ribbon cable. Carrier gets an SH-12 socket, not a pin header. |
| J8 pinout | 1 GND · 2 **USB_5V** · 3 D− (IO19) · 4 D+ (IO20) · 5 GND · 6 3V3 · 7 SCL (IO10) · 8 SDA (IO11) · 9 UART_TXD (IO43) · 10 UART_RXD (IO44) · 11 **GPIO18** · 12 **GPIO15** | 5 V in, I²C, two spare GPIOs and UART all on one cable. |
| USB → system | USB_5V → **D3 B5819WS** Schottky → VCC → **ME6217C33** LDO → 3V3 | USB has priority; VCC ≈ USB_5V − 0.3 V. D3 blocks back-feed from the battery rail to USB_5V. |
| Battery → system | BAT → **Q1 AO3401** (gate: R2 100 k pull-up to BAT, pulled low by **T2** when `BAT_Control` = IO7 high, or by Key1) → **Q2 AO3401** (gate = USB_5V, R29 100 k to GND) → VCC | Battery path is enabled only when USB is absent **and** firmware has driven IO7 high. Q2's body diode also conducts BAT→VCC once VCC drops ~0.6 V below BAT. |
| Charger | **ETA6098** switching Li-ion charger, VIN = USB_5V, **RISET R7 = 82 kΩ → 2 A** fast charge, CV 4.2 V, termination 130 mA, restart at −160 mV, input 4.5–5.5 V (32 V standoff) | Charges whatever sits on the battery connector to 4.2 V with its own current limit. |
| Battery connector | J1 **PH1.25 2-pin**, BAT / GND | Where the supercap bank plugs in. |
| BAT_ADC | IO8 reads BAT through 200 k / 100 k | Firmware can read the supercap voltage: Vbat = 3 × Vadc. |
| Backlight | NPN T3 on **IO5** | Brownout handler cuts it first. |
| Antenna | ceramic chip antenna (J4, CA-C03) + U.FL (J3), at the **top-left corner** of the module (back view: ESP32 module upper-left, USB-C bottom centre) | Copper keep-out on the carrier under that corner. |
| Mechanical | PCB 69.00 × 49.90 mm, glass 73.06 × 50.54 mm, total 10.0 mm thick, **6.0 mm of components on the back**. Holes: 4, on a **60.00 × 41.00 mm** grid, **4.50 mm** from the PCB edges; 4.3 mm ring in the STEP, drill ≈ 2.7 mm (M2.5). | Carrier outline and holes copy these; standoffs ≥ 8 mm. |

## Power design (Rev 2, default configuration)

Schematic: `carrier/carrier.kicad_sch` (KiCad 10 project `carrier/carrier.kicad_pro`).

```
car USB ─ J1 USB-C ─ F1 PTC 1.1 A ─┬─ TVS1 SMAJ5.0A ─ GND
            VIN_CAR      VIN_FUSED ├─ R8 4k7 bleeder ─ GND
                                   ├─ R1 100k ─┬─ R2 11k3 ─ GND
                                   │           └─ U2 TPS3808G01 SENSE      ~RESET → J3.12 (IO15) = PWR_SENSE
                                   │              (VDD = module 3V3 via J3.6, C3 100n)
                                   └─ D1 SS34 ∥ JP1 (bridged) ─┬─ C2 10µF   USB_5V → J3.2
                                                               └─ TP1

module J1 (BAT) ─ cable ─ J5 PicoBlade ─ JP2 (bridged) ─ C1 5F/2.7V ─┬─ C4 5F/2.7V ─ GND
                                                          R4 10k ∥ C1  R5 10k ∥ C4
```

- The module's **ETA6098 charges the 2 × 5 F bank to 4.2 V** (2.5 F usable, 5.4 V rated). Charge time from empty at 2 A: about 5 s. With a weak car port the charger's 4.5 V UVLO throttles it; the board keeps running from USB_5V via D3 regardless.
- When the car cuts power: USB_5V collapses (R8 bleeds it down; the module's D3 stops the board holding it up), Q2 turns on, VCC = BAT, and the board runs from the supercaps. **Hold-up ≈ 5–7 s** with the backlight off (2.5 F × (4.2 − 3.6 V) ÷ 0.2 A ≈ 7 s if the bank starts at 4.2 V; the charger only restarts after a 160 mV drop, so it can sit at ~4.04 V). The ride write takes well under a second.
- **Power-loss sense (U2).** A TPS3808G01 supervisor watches VIN_FUSED through R1/R2 and drives IO15 with its open-drain `~RESET`; the module's R30 10 k on IO15 is the pull-up. Trip ≈ 0.405 V × (1 + 100 k / 11.3 k) = **3.99 V falling**; `~RESET` releases 20 ms after VIN_FUSED is back above that (CT open). U2 runs from the module's 3V3, which the supercaps hold up, so IO15 stays actively low after the car port is gone. A supervisor powered from the car rail would leave its output undefined below ~1 V, and R30 would then pull IO15 high again during the hold-up. This replaces the first draft's 100 k / 47 k divider, which R30 kept above the HIGH threshold with the car on *or* off.
- **JP1 is bridged by default** (D1 bypassed): D1's drop plus the PTC and cable would leave ~4.4 V at J8, below the ETA6098's 4.5 V minimum input. D1 only matters in the fallback configuration.
- **Firmware must drive IO7 (`BAT_Control`) high at boot** and never low; otherwise Q1 stays off and the caps are useless. Waveshare's examples do this.
- Nothing on the carrier limits or switches the cap current: the module does. The carrier's job is protection (F1, TVS1), sensing (U2), balancing (R4/R5) and connectors.
- **Charge current through J8.** Everything the module draws, including up to 2 A of ETA6098 charge current, enters through J8 pin 2: one SH contact rated about 1 A, and F1 holds 1.1 A. Before the first car test, change the module's R7 (ETA6098 RISET, 0402 on the back) from 82 k to **≥ 200 k (≈ 0.8 A)**. Recharging an empty bank then takes ~15 s instead of ~5 s, which doesn't matter.
- The module's microSD slot shares IO15 (SD_D2): leave it empty or use 1-bit SD mode.

### Fallback configuration (if the bench test shows the charger misbehaving with a capacitor)

Footprints are on the board for the Rev 1 circuit: **R3 22 Ω 1 W** from USB_5V to VCAP and **D2 SS34** from VCAP back to USB_5V (both DNP). To use it: cut JP1 (so D1 blocks back-feed into the car port), cut JP2, leave J5 unconnected, populate R3 and D2. The caps then charge to ~4.7 V on the 5 V side and discharge into USB_5V through D2. Hold-up ≈ 2.5 F × (4.4 − 3.9 V) ÷ 0.2 A ≈ 6 s (two diode drops cost margin).
A gentler alternative is the R7 change above (≥ 200 k).

## Carrier PCB nets (rev A)

Source of truth: `carrier/carrier.kicad_sch` (ERC clean). This table is a summary.

| Net | Pins |
| --- | --- |
| VIN_CAR | J1 VBUS (A4, A9, B4, B9) → F1.1 |
| VIN_FUSED | F1.2, TVS1 K, D1 A, JP1.1, R1.1, R8.1 |
| USB_5V | D1 K, JP1.2, C2.1, R3.1 (fallback), D2 K (fallback), J3.2, TP1 |
| SENSE_DIV | R1.2, R2.1, U2.5 SENSE |
| PWR_SENSE | U2.1 ~RESET, J3.12 |
| BAT | J5.1, JP2.1 |
| VCAP | JP2.2, C1 +, R4.1, R3.2 (fallback), D2 A (fallback), TP2 |
| VCAP_MID | C1 −, C4 +, R4.2, R5.1 |
| +3V3 | J3.6, J2.1, U2.6 VDD, U2.3 ~MR, C3.1 |
| SCL | J3.7, J2.4 |
| SDA | J3.8, J2.3 |
| NFC_IRQ | J2.5, J3.11 |
| UART_TX / UART_RX | J3.9 / J3.10 → J4.1 / J4.2 |
| USB_CC1 / USB_CC2 | J1 A5 / B5 → R6 / R7 5.1 k → GND |
| GND | J1 GND + shell, TVS1 A, R2.2, R8.2, C4 −, R5.2, R6.2, R7.2, C2.2, C3.2, U2.2, J2.2, J3.1, J3.5, J3.MP, J4.3, J5.2, J5.MP, H1–H4 |

J3.3 and J3.4 (USB D±) and U2.4 CT (open = 20 ms release delay) are not connected.

## Connectors and cables

| Ref | Part | Mates with | Cable |
| --- | --- | --- | --- |
| J3 | JST **SM12B-SRSS-TB** (SH 1.0 mm, 12-pin, side entry) | module J8 | 12-way SH ribbon, 80–120 mm, **same-side (type A)** so pin 1 maps to pin 1. Check with a multimeter before first power-up. |
| J5 | Molex **53261-0271** (PicoBlade 1.25 mm, 2-pin, SMD right angle). The module's J1 is labelled "PH1.25 2P", which is the MX1.25 / PicoBlade-compatible part, not JST PH (2.0 mm) or GH. | module J1 (BAT) | 2-way 1.25 mm (Molex 51021-0200 housings both ends), 80 mm. Mind polarity: module J1 pin 1 = BAT. |
| J2 | JST **S5B-PH-K-S** (PH 2.0 mm, 5-pin, right angle) | PN532 module | 5-way PH to Dupont/pin header, 150–250 mm. |
| J1 | USB-C 16-pin receptacle (power-only wiring) | car USB cable | — |
| J4 | 1 × 3 2.54 mm header | USB-UART dongle | — |

## Mechanical and layout

- Outline **69.00 × 49.90 mm**, R2.0 corners. Holes **Ø2.7 mm at (4.50, 4.50), (64.50, 4.50), (4.50, 45.50), (64.50, 45.50)** in module coordinates (origin = module PCB bottom-left as seen from the back).
- Stack: module on top, carrier behind it on **8 mm M2.5 standoffs** (module back-side components are 6 mm tall; USB-C and SH sockets sit along the module's edges).
- Supercaps (Ø8 × 20 mm) mount on the **outer face** of the carrier (away from the module), lying flat, or standing if the enclosure is deep enough.
- **Copper keep-out** on both carrier layers under the module's antenna: a 25 × 12 mm zone at the top-left corner of the module footprint. Mark it on the carrier silkscreen.
- Carrier USB-C on the same edge as the module's USB-C (bottom), so both face the same cable channel.
- J3 (SH-12) near the module's J8 position: module back view, lower-left quadrant, about 12 mm from the left edge.
- Power path traces (VIN_CAR → F1 → D1/JP1 → J3.2; BAT → J5 → caps) 0.6 mm (the most J3 and J1 pads allow; widen long runs where there is room). Keep U2, R1/R2 and C3 close together, away from the caps' current loop. Ground pour both sides, stitched.
- Silkscreen: pin 1 marks on J3/J5/J2, cap polarity, JP1/JP2 meaning, `car-km carrier rev A`.

### Board status (`carrier/carrier.kicad_pcb`, first pass, 2026-10-06)

Placed, routed, and DRC clean in KiCad 10: 0 errors, 0 unconnected, 0 schematic-parity issues. The only warnings are J1's own silkscreen running off the edge where the receptacle overhangs. Not reviewed by a human yet, and nothing has been sent to a fab.

- **Orientation:** KiCad top view = carrier outer face = module back view (antenna top-left, USB-C bottom). Every part is on F.Cu, the outer face; the face toward the module stays empty because the module's back parts leave only ~2 mm under 8 mm standoffs.
- **Edges:**
  - J1 USB-C on the bottom edge (x ≈ 32 mm, close under the module's USB-C).
  - J3 SH-12 on the left edge, opening outward; the SH cable wraps round the carrier edge to module J8.
  - J5 PicoBlade on the right edge.
  - J2 PH-5 on the top edge, right of the antenna keep-out.
  - J4 UART header bottom right.
- **Holes:** H1, top-left inside the antenna keep-out, is a bare NPTH (`MountingHole_2.7mm_M2.5`, no copper). H2–H4 are plated and tied to GND.
- **Rules:** net classes are in the project file: Power 0.6 mm / 0.8 mm vias (VIN_CAR, VIN_FUSED, USB_5V, BAT, VCAP, VCAP_MID), GND 0.4 mm, signals 0.25 mm, 0.2 mm clearance. 0.6 mm is the most that fits J3's 1.0 mm-pitch pads and J1's VBUS pins. That is plenty for ~1 A, but widen the long runs by hand if you want margin. Minimum track width is 0.15 mm because the router necks +3V3 into U2's SOT-23 pads.
- **GND:** pours on both layers, a fan-out via next to every SMD GND pad, and stitching vias. F.Cu has track keep-outs under the J1, J3 and J5 bodies; the antenna keep-out blocks copper on both layers.
- **Routing:** autorouted with Freerouting 2.5 through Specctra DSN/SES, with GND excluded so the pours carry it. Expect to tidy a few routes by hand, e.g. the long USB_5V run to the DNP fallback R3/D2.
- **Before ordering:**
  - Review in KiCad.
  - Check the 3D fit against the Waveshare STEP (needs `kicad-packages3d` or the Windows KiCad's models).
  - Re-run DRC.
  - Export fab files: `kicad-cli pcb export gerbers` and `kicad-cli pcb export drill`.

## Firmware hooks (ESP-IDF, Waveshare BSP)

| Signal | GPIO | Use |
| --- | --- | --- |
| BAT_Control | IO7 | **Output high at boot**, first thing in `app_main`. Keeps Q1 on so the caps carry the board at power loss. |
| BAT_ADC | IO8 | ADC; Vbat = 3 × Vadc. Show "backup OK" when > 3.9 V; warn if the caps never reach 4.0 V. |
| PWR_SENSE | IO15 | Input, falling-edge ISR → brownout handler. |
| LCD_BL | IO5 | Backlight; set low in the brownout handler before any flash write. |
| NFC_IRQ | IO18 | Input, falling edge = PN532 has a tag. |
| I²C | IO10 SCL / IO11 SDA | Shared: PN532 0x24, PCF85063 0x51, QMI8658 0x6B. |
| Key_BAT | IO6 | Module's own button; unused. |

Brownout handler order: BL off → stop BLE polling → write `ride/live` → mark ride closed → halt (`while(1) vTaskDelay`). In the halt loop, if IO15 reads high again (ignition back while the caps still hold the board, so there is no power-on reset), call `esp_restart()`. U2's 20 ms release delay debounces that. On next boot a leftover `ride/live` is closed and queued (Rev 1 logic).

## Verified / still to verify

Verified from Waveshare files: J8 pitch and pinout, VBUS on J8, power path, charger current, mechanical outline and hole grid, antenna location.

- [ ] Hole drill diameter (STEP shows a 4.3 mm ring only): measure, or use Ø2.7 and M2.5 either way.
- [ ] Bench: caps on J1, USB in, watch BAT reach ~4.2 V (BAT_ADC or a meter); set IO7 high; pull USB; time until reset with backlight off. Target ≥ 5 s. Repeat with a 1 A-limited supply to emulate a weak car port.
- [ ] Bench: module current, backlight on/off, WiFi on/off (USB meter).
- [ ] SH cable type (same-side) confirmed with a meter before first power-up.
- [ ] Car USB dead at key-out.

## Bill of materials

`bom-rev2.csv`. Changes from the first Rev 2 draft: J3 is an SH-12 socket (not 2.54 mm), J5 1.25 mm PicoBlade added, D1 kept but bypassed by JP1 (bridged), R3/D2 kept only as fallback footprints, SH and 1.25 mm cables added.
Changes from the 2026-10-06 review (schematic rev A): U2 TPS3808G01 + C3 power-loss sense (R2 47 k → 11.3 k), R8 4.7 k bleeder, JP1 bridged by default, J5 = Molex 53261-0271, supercaps renamed C1a/C1b → C1/C4.

## Rev 2b (later)

PN532 chip + printed antenna on the carrier (NXP AN1445), needs a NanoVNA. Only after Rev 2 works.

Sources: Waveshare [ESP32-S3-Touch-LCD-2.8 wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-2.8) (schematic, 2D, STEP);
ETA6096 datasheet via [LCSC](https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/2307171444_etasolution-ETA6096D3K_C7465538.pdf) (same family as the ETA6098 on the module: RISET 82 k → 2 A, CV 4.2 V, 130 mA termination, 4.5–5.5 V input).
