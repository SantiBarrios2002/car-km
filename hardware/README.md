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
| Antenna | PCB antenna + U.FL (J3), at the **top-left corner** of the module (back view: ESP32 module upper-left, USB-C bottom centre) | Copper keep-out on the carrier under that corner. |
| Mechanical | PCB 69.00 × 49.90 mm, glass 73.06 × 50.54 mm, total 10.0 mm thick, **6.0 mm of components on the back**. Holes: 4, on a **60.00 × 41.00 mm** grid, **4.50 mm** from the PCB edges; 4.3 mm ring in the STEP, drill ≈ 2.7 mm (M2.5). | Carrier outline and holes copy these; standoffs ≥ 8 mm. |

## Power design (Rev 2, default configuration)

```
car USB ─ J1 USB-C ─ F1 PTC 1.1 A ─┬─ TVS1 SMAJ5.0A ─ GND
                                   ├─ R1 100k ─┬─ R2 47k ─ GND        PWR_SENSE → J3.12 (IO15)
                                   └─ D1 SS34 ─┬─ C2 10µF           USB_5V    → J3.2
                                               └─ (JP1 solder jumper bypasses D1 if its 0.3 V matters)

module J1 (BAT) ─ cable ─ J5 PH1.25 ─ JP2 ─ C1a 5F/2.7V ─┬─ C1b 5F/2.7V ─ GND
                                          R4 10k ∥ C1a    R5 10k ∥ C1b
```

- The module's **ETA6098 charges the 2 × 5 F bank to 4.2 V** (2.5 F usable, 5.4 V rated). Charge time from empty at 2 A: about 5 s. With a weak car port the charger's 4.5 V UVLO throttles it; the board keeps running from USB_5V via D3 regardless.
- When the car cuts power: USB_5V collapses (D1 stops the car-side capacitance holding it up), Q2 turns on, VCC = BAT, and the board runs from the supercaps. **Hold-up ≈ 2.5 F × (4.2 − 3.6 V) ÷ 0.2 A ≈ 7 s** with the backlight off. The ride write takes well under a second.
- `PWR_SENSE` on the **car side** of D1 tells IO15 the instant the port dies.
- **Firmware must drive IO7 (`BAT_Control`) high at boot** and never low; otherwise Q1 stays off and the caps are useless. Waveshare's examples do this.
- Nothing on the carrier limits or switches the cap current: the module does. The carrier's job is protection (F1, TVS1), isolation (D1), sensing (R1/R2), balancing (R4/R5) and connectors.

### Fallback configuration (if the bench test shows the charger misbehaving with a capacitor)

Footprints are on the board for the Rev 1 circuit: **R3 22 Ω 1 W** from USB_5V (after D1) to VCAP and **D2 SS34** from VCAP back to USB_5V. To use it: open JP2, leave J5 unconnected, populate R3 and D2. The caps then charge to ~4.7 V on the 5 V side and discharge into USB_5V through D2. Hold-up ≈ 2.5 F × (4.4 − 3.9 V) ÷ 0.2 A ≈ 6 s (two diode drops cost margin).
A gentler alternative is to change the module's R7 from 82 k to 150 k (1.2 A) or 200 k (~0.9 A); it's an 0402 on the back of the module.

## Carrier PCB nets (rev A)

See `carrier-netlist.net` (KiCad legacy netlist).

| Net | Pins |
| --- | --- |
| VIN_CAR | J1 VBUS (A4, A9, B4, B9) → F1.1 |
| VIN_FUSED | F1.2, TVS1 K, D1 A, R1.1, JP1.1 |
| USB_5V | D1 K, JP1.2, C2.1, R3.1 (fallback), D2 K (fallback), J3.2, TP1 |
| PWR_SENSE | R1.2, R2.1, J3.12 |
| BAT | J5.1, JP2.1 |
| VCAP | JP2.2, C1a +, R4.1, R3.2 (fallback), D2 A (fallback), TP2 |
| VCAP_MID | C1a −, C1b +, R4.2, R5.1 |
| 3V3 | J3.6, J2.1 |
| SCL | J3.7, J2.4 |
| SDA | J3.8, J2.3 |
| NFC_IRQ | J2.5, J3.11 |
| UART_TX / UART_RX | J3.9 / J3.10 → J4.1 / J4.2 |
| USB_CC1 / USB_CC2 | J1 A5 / B5 → R6 / R7 5.1 k → GND |
| GND | J1 GND + shell, TVS1 A, R2.2, C1b −, R5.2, R6.2, R7.2, C2.2, J2.2, J3.1, J3.5, J4.3, J5.2 |

J3.3 and J3.4 (USB D±) are not connected.

## Connectors and cables

| Ref | Part | Mates with | Cable |
| --- | --- | --- | --- |
| J3 | JST **SM12B-SRSS-TB** (SH 1.0 mm, 12-pin, side entry) | module J8 | 12-way SH ribbon, 80–120 mm, **same-side (type A)** so pin 1 maps to pin 1. Check with a multimeter before first power-up. |
| J5 | JST **S2B-PH-SM4-TB** or an MX1.25 / "PH1.25" 2-pin matching the module's J1 | module J1 (BAT) | 2-way 1.25 mm, 80 mm. Mind polarity: module J1 pin 1 = BAT. |
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
- Power path traces (VIN_CAR → F1 → D1 → J3.2; BAT → J5 → caps) 1.0 mm. Ground pour both sides, stitched.
- Silkscreen: pin 1 marks on J3/J5/J2, cap polarity, JP1/JP2 meaning, `car-km carrier rev A`.

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

Brownout handler order: BL off → stop BLE polling → write `ride/live` → mark ride closed → `esp_restart()` is *not* called; just halt (`while(1) vTaskDelay`). On next boot a leftover `ride/live` is closed and queued (Rev 1 logic).

## Verified / still to verify

Verified from Waveshare files: J8 pitch and pinout, VBUS on J8, power path, charger current, mechanical outline and hole grid, antenna location.

- [ ] Hole drill diameter (STEP shows a 4.3 mm ring only): measure, or use Ø2.7 and M2.5 either way.
- [ ] Bench: caps on J1, USB in, watch BAT reach ~4.2 V (BAT_ADC or a meter); set IO7 high; pull USB; time until reset with backlight off. Target ≥ 5 s. Repeat with a 1 A-limited supply to emulate a weak car port.
- [ ] Bench: module current, backlight on/off, WiFi on/off (USB meter).
- [ ] SH cable type (same-side) confirmed with a meter before first power-up.
- [ ] Car USB dead at key-out.

## Bill of materials

`bom-rev2.csv`. Changes from the first Rev 2 draft: J3 is an SH-12 socket (not 2.54 mm), J5 PH1.25 added, D1 kept but jumper-bypassable, R3/D2 kept only as fallback footprints, SH and 1.25 mm cables added.

## Rev 2b (later)

PN532 chip + printed antenna on the carrier (NXP AN1445), needs a NanoVNA. Only after Rev 2 works.

Sources: Waveshare [ESP32-S3-Touch-LCD-2.8 wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-2.8) (schematic, 2D, STEP);
ETA6096 datasheet via [LCSC](https://wmsc.lcsc.com/wmsc/upload/file/pdf/v2/lcsc/2307171444_etasolution-ETA6096D3K_C7465538.pdf) (same family as the ETA6098 on the module: RISET 82 k → 2 A, CV 4.2 V, 130 mA termination, 4.5–5.5 V input).
