# car-km hardware — Rev 2: Waveshare ESP32-S3-Touch-LCD-2.8 + carrier PCB

The car device is an off-the-shelf **Waveshare ESP32-S3-Touch-LCD-2.8** (ESP32-S3, 2.8" touch display, RTC, Li-ion charger) mounted on a small custom **carrier PCB**. The carrier takes 5 V from the car's USB port, holds the module up for a few seconds after the ignition cuts power (so the ride can be saved), tells the firmware when that happens, and breaks out the PN532 NFC reader and a debug UART. Distance comes from a **Vgate iCar Pro** BLE OBD-II dongle, which needs no wiring.

## Status

| Item | State |
| --- | --- |
| Module facts | Verified against Waveshare's schematic and 2D drawing (`vendor/`), 2026-10-06. |
| Carrier schematic | `carrier/carrier.kicad_sch`, KiCad 10, ERC clean (0 violations). |
| Carrier PCB | `carrier/carrier.kicad_pcb`, first pass: placed, autorouted, DRC clean. **Not reviewed by a person, not ordered.** |
| Parts | Nothing bought yet except the OBD dongle (`bom-rev2.csv`). |

## Next step: pre-order checks

None of these have been done yet. Work through them in order before sending anything to a fab. All commands run from the repo root.

**1. Review the board in KiCad.** Open `hardware/carrier/carrier.kicad_pro`, then the PCB editor. Look at:
- **Routing:** the signals were autorouted (Freerouting) and nobody has looked at them yet. Tidy anything odd, especially the long USB_5V run to the fallback R3/D2. Those two parts aren't fitted by default, so that track could be shortened or moved.
- **Power trace widths:** 0.6 mm, which is the most J3's 1.0 mm-pitch pads and J1's VBUS pins allow. Widen the open runs (J1 → F1 → D1/JP1 → J3, J5 → JP2 → caps) where there is room.
- **Connector positions** against the real stack (see step 2): J1 on the bottom edge, J3 on the left edge, J5 on the right edge, J2 on the top edge.
- **Silkscreen:** pin-1 marks, cap polarity, the JP1/JP2 notes.
- After any edit, refill zones (`B`) before checking.

**2. Check the 3D fit.**
- Install the 3D models (`sudo apt install kicad-packages3d`, or use a KiCad install that has them).
- Download `ESP32-S3-Touch-LCD-2.8_3D.zip` from the [Waveshare wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-2.8) into `vendor/`. Don't commit it; it's 20 MB.
- Export the carrier: `kicad-cli pcb export step --subst-models -o hardware/carrier/carrier.step hardware/carrier/carrier.kicad_pcb`.
- Combine the two in FreeCAD (or the KiCad 3D viewer): the module sits on top, parts side facing the carrier, on 8 mm standoffs. Check:
  - **The gap between the boards.** The module's back parts are 6 mm tall, so about 2 mm is left. The carrier's inner face has no parts, but the through-hole leads of J2, J4, C1 and C4 stick out of it: trim them flush or check they clear.
  - **Total depth:** module 10 mm + standoffs 8 mm + carrier 1.6 mm + supercaps 20 mm standing (or ~9 mm lying flat).
  - **Cable paths:**
    - SH-12 cable from J3 round the left edge to module J8, which is in the lower-left quadrant of the module's back, about 12 mm from its left edge;
    - 2-pin cable from J5 to module J1 (BAT);
    - PN532 cable from J2.
  - **USB-C clearance:** a plug in the carrier's J1 near the module's own USB-C, which sits bottom centre.

**3. Re-run ERC and DRC** after any change:

```bash
kicad-cli sch erc --severity-all -o /tmp/erc.rpt hardware/carrier/carrier.kicad_sch
kicad-cli pcb drc --schematic-parity --severity-all -o /tmp/drc.rpt hardware/carrier/carrier.kicad_pcb
```

Expected: ERC 0 violations; DRC 0 errors, 0 unconnected, 0 parity issues. Two warnings are accepted: J1's library silkscreen runs off the board edge where the receptacle overhangs it.

**4. Export the fab files and inspect them.**

```bash
mkdir -p hardware/carrier/fab
kicad-cli pcb export gerbers --check-zones -l F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
  -o hardware/carrier/fab/ hardware/carrier/carrier.kicad_pcb
kicad-cli pcb export drill --excellon-separate-th --generate-map -o hardware/carrier/fab/ hardware/carrier/carrier.kicad_pcb
```

Open the result in `gerbview` (ships with KiCad) or the fab's online viewer before uploading. The board is 2 layers, 1.6 mm, 69.0 × 49.9 mm, with a 0.2 mm minimum clearance and 0.15 mm minimum track (standard JLCPCB/PCBWay rules). `fab/` is not committed.

**After the boards arrive** (before the first car test):
- Change the module's R7 to ≥ 200 kΩ (see *Charge current*).
- Do the bench checks under *Still to verify*.

## The Waveshare module (from its schematic)

| Item | Fact | Consequence |
| --- | --- | --- |
| J8 "12-pin header" | **JST SH 1.0 mm, 12 pins** (`SH1.0-12P`) | The carrier connects with a 12-way SH cable; its J3 is an SH-12 socket. |
| J8 pinout | 1 GND · 2 **USB_5V** · 3 D− (IO19) · 4 D+ (IO20) · 5 GND · 6 3V3 · 7 SCL (IO10) · 8 SDA (IO11) · 9 UART_TXD (IO43) · 10 UART_RXD (IO44) · 11 **GPIO18** · 12 **GPIO15** | 5 V in, I²C, two spare GPIOs and UART on one cable. |
| USB → system | USB_5V → **D3 B5819WS** Schottky → VCC → **ME6217C33** LDO → 3V3 | USB has priority; VCC ≈ USB_5V − 0.3 V. D3 stops the battery rail back-feeding USB_5V. |
| Battery → system | BAT → **Q1 AO3401** (gate: R2 100 k to BAT, pulled low by **T2** when `BAT_Control` = IO7 is high, or by Key1) → **Q2 AO3401** (gate = USB_5V, R29 100 k to GND) → VCC | The battery path is on only when USB is absent **and** the firmware has driven IO7 high. Q2's body diode also conducts once VCC drops ~0.6 V below BAT. |
| Charger | **ETA6098** switching Li-ion charger, input = USB_5V, **RISET R7 = 82 kΩ → 2 A**, CV 4.2 V, 130 mA termination, restarts at −160 mV, input 4.5–5.5 V | Charges whatever is on the battery connector to 4.2 V. |
| Battery connector | J1, labelled **"PH1.25 2P"**: the 1.25 mm MX1.25 / Molex PicoBlade-compatible part (not JST PH 2.0 or GH). Pin 1 = BAT. | The supercap bank plugs in here, via the carrier's J5. |
| Pull-ups | R30 10 k to 3V3 on IO15 (SD_D2), R35 10 k on IO18 (SD_D1) | IO15 already has a pull-up, so the power-loss sense must drive it actively low. |
| BAT_ADC | IO8 reads BAT through 200 k / 100 k | Vbat = 3 × Vadc. |
| Backlight | NPN T3 on **IO5** | Turned off first when power is lost. |
| Antenna | Ceramic chip antenna (CA-C03) + U.FL, **top-left corner** in back view (ESP32 module upper-left, USB-C bottom centre) | Copper keep-out on the carrier under that corner. |
| Mechanical | PCB 69.00 × 49.90 mm, glass 73.06 × 50.54 mm, 10.0 mm total, **6.0 mm of parts on the back**. 4 holes on a **60.00 × 41.00 mm** grid, 4.50 mm in from the edges, Ø ≈ 2.7 mm (M2.5) | The carrier copies the outline and holes; standoffs ≥ 8 mm. |

## Carrier design

Schematic: `carrier/carrier.kicad_sch` (the source of truth for every net).

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

The carrier only protects (F1, TVS1), senses (U2), balances (R4/R5) and connects. Charging and switching to the caps happen on the module.

- **Hold-up.** The module's ETA6098 charges the 2 × 5 F bank (2.5 F, 5.4 V rated) to 4.2 V. When the car cuts power, USB_5V collapses (R8 bleeds it down; the module's D3 stops the board holding it up), Q2 turns on and the board runs from the caps. **Hold-up ≈ 5–7 s** with the backlight off: 2.5 F × (4.2 − 3.6 V) ÷ 0.2 A ≈ 7 s from a full bank, less because the charger only tops up after a 160 mV drop (~4.04 V). Saving the ride takes well under a second.
- **Power-loss sense (U2).** A TPS3808G01 supervisor watches VIN_FUSED through R1/R2 and drives IO15 low with its open-drain `~RESET`; the module's R30 is the pull-up.
  - Trip point: 0.405 V × (1 + 100 k / 11.3 k) = **3.99 V falling**. `~RESET` releases 20 ms after VIN_FUSED recovers (CT open).
  - U2 runs from the module's 3V3, which the caps hold up, so IO15 stays low for the whole hold-up. A supervisor powered from the car side would let IO15 float back high once the car rail fell below ~1 V.
  - A plain resistor divider can't do this job: R30 keeps IO15 high whether the car is on or off.
- **JP1 is bridged by default** (D1 bypassed). D1's drop plus the PTC and cable would leave ~4.4 V at J8, below the ETA6098's 4.5 V minimum input. D1 only matters in the fallback configuration.
- **Charge current.** Everything the module draws, up to 2 A of charge current included, comes in through J8 pin 2: one SH contact rated about 1 A, behind F1 (1.1 A hold). **Change the module's R7 (0402, back side) from 82 k to ≥ 200 k (≈ 0.8 A)** before the first car test. Recharging an empty bank then takes ~15 s instead of ~5 s.
- **Firmware duties:** drive IO7 (`BAT_Control`) high at boot and never low, otherwise the caps are never connected. Leave the microSD slot empty or use 1-bit SD mode, because IO15 is also SD_D2.

### Fallback configuration

This is for the case where the bench test shows the module's charger misbehaving with a capacitor load. Footprints for the Rev 1 circuit are on the board, unpopulated (DNP):
- **R3** (22 Ω, 1 W) from USB_5V to VCAP;
- **D2** (SS34) from VCAP back to USB_5V.

To switch over:
1. Cut JP1, so that D1 blocks back-feed into the car port.
2. Cut JP2.
3. Leave J5 unconnected.
4. Fit R3 and D2.

The caps then charge to ~4.7 V from the 5 V side and discharge into USB_5V through D2. Hold-up ≈ 2.5 F × (4.4 − 3.9 V) ÷ 0.2 A ≈ 6 s.

### Nets (summary)

| Net | Pins |
| --- | --- |
| VIN_CAR | J1 VBUS (A4, A9, B4, B9), F1.1 |
| VIN_FUSED | F1.2, TVS1 K, D1 A, JP1.1, R1.1, R8.1 |
| USB_5V | D1 K, JP1.2, C2.1, J3.2, TP1, R3.1 (DNP), D2 K (DNP) |
| SENSE_DIV | R1.2, R2.1, U2.5 SENSE |
| PWR_SENSE | U2.1 ~RESET, J3.12 |
| BAT | J5.1, JP2.1 |
| VCAP | JP2.2, C1 +, R4.1, TP2, R3.2 (DNP), D2 A (DNP) |
| VCAP_MID | C1 −, C4 +, R4.2, R5.1 |
| +3V3 | J3.6, J2.1, U2.6 VDD, U2.3 ~MR, C3.1 |
| SCL / SDA | J3.7 / J3.8 → J2.4 / J2.3 |
| NFC_IRQ | J3.11, J2.5 |
| UART_TX / UART_RX | J3.9 / J3.10 → J4.1 / J4.2 (module TXD / RXD) |
| USB_CC1 / USB_CC2 | J1 A5 / B5 → R6 / R7 5.1 k → GND |
| GND | J1 GND + shell, TVS1 A, R2, R5, R6, R7, R8, C2, C3, C4 −, U2.2, J2.2, J3.1, J3.5, J3/J5 mounting tabs, J4.3, J5.2, H2–H4 |

Not connected: J3.3 / J3.4 (USB D±), U2.4 CT (open = 20 ms delay), J1 D± and SBU. H1 is a bare hole.

### Connectors and cables

| Ref | Part | Mates with | Cable |
| --- | --- | --- | --- |
| J1 | USB-C 16-pin receptacle (HRO TYPE-C-31-M-12), power only | car USB cable | — |
| J3 | JST **SM12B-SRSS-TB** (SH 1.0 mm, 12-pin, side entry) | module J8 | 12-way SH, 80–120 mm, **same-side (type A)** so pin 1 maps to pin 1. Check with a meter before first power-up. |
| J5 | Molex **53261-0271** (PicoBlade 1.25 mm, 2-pin, SMD right angle) | module J1 (BAT) | 2-way 1.25 mm (Molex 51021-0200 housing both ends), 80 mm. Mind polarity: pin 1 = BAT on both. |
| J2 | JST **S5B-PH-K-S** (PH 2.0 mm, 5-pin, right angle) | PN532 module (DIP switch set to I²C) | 5-way PH to Dupont, 150–250 mm. Pins: 3V3, GND, SDA, SCL, IRQ. |
| J4 | 1 × 3 2.54 mm header | USB-UART dongle | J4.1 = module TX → dongle RX, J4.2 = module RX ← dongle TX, J4.3 = GND. |

## PCB layout (`carrier/carrier.kicad_pcb`)

- **Outline and stack:**
  - 69.00 × 49.90 mm, R2 corners, 2 layers, 1.6 mm.
  - The module sits on top, parts side down, on **8 mm M2.5 standoffs**; the carrier is behind it.
  - KiCad's top view is the carrier's outer face, which matches the module's back view: antenna top-left, USB-C bottom.
- **All parts are on the outer face** (F.Cu). The inner face stays empty because only ~2 mm is left under the module's 6 mm-tall back parts.
- **Holes:** Ø2.7 at (4.5, 4.5), (64.5, 4.5), (4.5, 45.5), (64.5, 45.5) in module coordinates (origin at the bottom-left, back view).
  - H1, top-left, sits inside the antenna keep-out and is a bare NPTH with no copper.
  - H2–H4 are plated and tied to GND.
- **Antenna keep-out:** 25 × 12 mm in the top-left corner, no copper on either layer, outlined on the silkscreen.
- **Placement:**
  - edges: J1 on the bottom edge, J3 on the left edge (opening outward, cable wraps round to J8), J5 on the right edge, J2 on the top edge right of the keep-out;
  - J4 bottom right;
  - supercaps C1/C4 top right;
  - car-input parts (F1, TVS1, D1/JP1) between J1 and J3;
  - sense circuit (U2, R1/R2, C3) next to J3.
- **Net classes** (stored in `carrier.kicad_pro`):

  | Class | Track | Via | Nets |
  | --- | --- | --- | --- |
  | Power | 0.6 mm | 0.8 / 0.4 mm | VIN_CAR, VIN_FUSED, USB_5V, BAT, VCAP, VCAP_MID |
  | GND | 0.4 mm | 0.6 / 0.3 mm | GND |
  | Default | 0.25 mm | 0.6 / 0.3 mm | all signals |

  Clearance is 0.2 mm everywhere. The 0.15 mm minimum track width allows the necked-down +3V3 entry into U2's SOT-23 pads.
- **GND:**
  - pours on both layers;
  - a fan-out via next to every SMD GND pad;
  - stitching vias across the board.
  F.Cu has track keep-outs under the J1, J3 and J5 bodies.
- **Routing:** Freerouting 2.5 via Specctra DSN/SES, with GND left to the pours. This is a first pass to tidy by hand (step 1 of the pre-order checks).

## Firmware hooks (ESP-IDF, Waveshare BSP)

| Signal | GPIO | Use |
| --- | --- | --- |
| BAT_Control | IO7 | **Output high at boot**, first line of `app_main`. Keeps Q1 on so the caps carry the board when power is lost. |
| BAT_ADC | IO8 | Vbat = 3 × Vadc. Show "backup OK" above 3.9 V; warn if the caps never reach 4.0 V. |
| PWR_SENSE | IO15 | Input; falling edge = car power lost → brownout handler. |
| LCD_BL | IO5 | Backlight; switched off first in the brownout handler. |
| NFC_IRQ | IO18 | Input; falling edge = PN532 has a tag. |
| I²C | IO10 SCL / IO11 SDA | Shared: PN532 0x24, PCF85063 RTC 0x51, QMI8658 IMU 0x6B. |
| Key_BAT | IO6 | Module button; unused. |

Brownout handler: backlight off → stop BLE polling → write `ride/live` → mark the ride closed → halt (`while (1) vTaskDelay`). In the halt loop, if IO15 reads high again (ignition back on while the caps still hold the board, so no power-on reset happens), call `esp_restart()`; U2's 20 ms release delay debounces this. On the next boot a leftover `ride/live` is closed and queued.

## Still to verify

Verified from Waveshare's files: J8 pitch and pinout, USB_5V on J8, power path, charger current, outline and hole grid, antenna position, IO15/IO18 pull-ups.

- [ ] Hole diameter: the STEP only shows a 4.3 mm ring. Measure it, or use Ø2.7 / M2.5 either way.
- [ ] Bench, supercaps:
  1. Caps on module J1, USB in; BAT should reach ~4.2 V (BAT_ADC or a meter).
  2. Set IO7 high, pull USB and time the hold-up with the backlight off. Target ≥ 5 s.
  3. Repeat on a 1 A-limited supply to imitate a weak car port.
- [ ] Bench: module current with backlight on/off and WiFi on/off (USB meter).
- [ ] SH cable is same-side (type A): check with a meter before first power-up.
- [ ] The car's USB port really goes dead at key-out.

## Bill of materials

`bom-rev2.csv`. Revision notes:
- **First Rev 2 draft:**
  - J3 is an SH-12 socket (not 2.54 mm);
  - J5 1.25 mm added;
  - D1 kept but bypassable;
  - R3/D2 kept as fallback footprints;
  - SH and 1.25 mm cables added.
- **2026-10-06 review (schematic rev A):**
  - U2 TPS3808G01 + C3 power-loss sense (R2 47 k → 11.3 k);
  - R8 4.7 k bleeder;
  - JP1 bridged by default;
  - J5 = Molex 53261-0271;
  - supercaps renamed C1a/C1b → C1/C4;
  - H1 changed to a bare NPTH;
  - holes, jumpers and test points dropped from the BOM.

## Later: Rev 2b

PN532 chip with a printed antenna on the carrier (NXP AN1445). This needs a NanoVNA for antenna tuning, and only makes sense once Rev 2 works.

## Sources

- Waveshare [ESP32-S3-Touch-LCD-2.8 wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-2.8): schematic and 2D drawing, copied into `vendor/` as `ESP32-S3-Touch-LCD-2.8_schematic.pdf` and `ESP32-S3-Touch-LCD-2.8_2D.pdf`; STEP model (not committed).
- ETA6096 datasheet via [LCSC](https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/2307171444_etasolution-ETA6096D3K_C7465538.pdf). It is the same family as the module's ETA6098: RISET 82 k → 2 A, CV 4.2 V, 130 mA termination, 4.5–5.5 V input.
- TI TPS3808 datasheet: adjustable version (G01) with a 0.405 V threshold, open-drain `~RESET`, CT open = 20 ms delay.
