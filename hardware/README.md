# car-km hardware — Rev 2: Waveshare display module + carrier PCB

Status: **design, nothing ordered**. Full write-up with diagrams lives in the build-spec doc
(tab "Rev 2: Waveshare + carrier PCB"); this file is the repo copy of the decisions and the numbers.

## Decision

| Role | Part | Why |
| --- | --- | --- |
| Brain + screen | Waveshare **ESP32-S3-Touch-LCD-2.8** (touch version) | 2.8" 240×320 IPS readable from the driver seat; PCF85063 RTC and PCM5101 audio amp onboard, so no DS3231 and no buzzer. ESP32-S3R8, 16 MB flash, 8 MB PSRAM, BLE 5. |
| Reader | **PN532 module "V3"** over I²C (addr 0x24) | The 2.8" board exposes only IO15, IO18, I²C and UART. I²C is exactly what the PN532 needs, and it also reads NTAG stickers and Android HCE. |
| Distance | Vgate iCar Pro BLE on the Meriva's OBD port | Unchanged from Rev 1: speed PID 0x0D at 1 Hz, integrated. |
| Carrier PCB | Custom, 2-layer, ~75 × 55 mm | Car-power protection, supercap hold-up, brownout sense, connectors. No MCU, nothing to tune. |

Spare GPIO budget on the Waveshare module: **IO15 = PWR_SENSE**, **IO18 = NFC_IRQ**. UART (IO43/44) stays free for debug. I²C (IO10/11) is shared with the module's RTC (0x51) and IMU (0x6B); PN532 at 0x24 does not collide.

## Power

Car USB (switched with ignition) → J1 USB-C → F1 PTC 1.1 A → TVS SMAJ5.0A → D1 SS34 → `V5_HOLD` → module VBUS pin.
`V5_HOLD` also charges a 2 × 5 F / 2.7 V supercap bank through R3 22 Ω (bypassed on discharge by D2 SS34).
A 100 k / 47 k divider on the **car side** of D1 drives IO15: 1.6 V while the car is on, 0 V within a millisecond of key-out.

Hold-up: 2.5 F × (4.4 − 3.5 V) ÷ 0.2 A ≈ **11 s** with the backlight off. The firmware's first act on the IO15 falling edge is backlight off, then write the ride, then halt.

Why not the module's battery connector: its charger expects a LiPo; behaviour with a 2.5 F "battery" is undocumented, and a LiPo in a parked car in August is unsafe. VBUS through our own circuit is fully under our control.

**Supercaps must be low-ESR cylindrical EDLC cells** (8 × 20 mm, ESR ≤ 0.5 Ω). Coin-stack "5.5 V 1 F" backup caps have 30–100 Ω ESR and collapse under load.

## Carrier PCB nets

See `carrier-netlist.net` (KiCad legacy netlist, import with *File → Import → Netlist* into an empty PCB, or read it as the schematic spec).

| Net | Pins |
| --- | --- |
| VIN_CAR | J1 VBUS (A4/A9/B4/B9) → F1.1 |
| VIN_FUSED | F1.2, TVS1 K, D1 A, R1.1 |
| V5_HOLD | D1 K, R3.1, D2 K, C2, C3, J3.VBUS |
| VCAP | R3.2, D2 A, C1a +, R4.1 |
| VCAP_MID | C1a −, C1b +, R4.2, R5.1 |
| PWR_SENSE | R1.2, R2.1, J3.IO15 |
| SDA / SCL | J3.SDA/SCL ↔ J2.3/J2.4 |
| NFC_IRQ | J2.5, J3.IO18 |
| 3V3 | J3.3V3, J2.1 |
| UART_TX / UART_RX | J3.TXD/RXD → J4 (optional) |
| GND | J1 GND, TVS1 A, R2.2, C1b −, R5.2, C2, C3, J2.2, J3 GND ×2, J4 GND |

USB-C power-only: CC1 and CC2 each to GND via 5.1 kΩ (so C-to-C car cables deliver 5 V). D+/D− unconnected.

J3 follows the Waveshare 12-pin header order: GND, VBUS, D−, D+, GND, 3V3, SCL, SDA, TXD, RXD, IO18, IO15.

## Layout rules

- Outline and 4 × M2.5 holes copy the Waveshare module; module sits above on 6 mm standoffs, J3 under its header.
- Power path in 1.0 mm traces; ground pour both layers, stitched.
- Supercaps upright at the edge away from J1 (20 mm tall), or flat if the box is shallow.
- **No copper pour under the module's PCB antenna** (the USB-C end of the Waveshare board). Verify position from the Waveshare drawing.
- J2 on the top edge; PN532 antenna ≥ 15 mm from the speaker magnet and from ground pour.
- Silkscreen: net names on J2/J4, supercap polarity, `car-km carrier rev A`.

## Verify before ordering the PCB

- [ ] 12-pin header pitch (assumed 2.54 mm) and whether pre-soldered — wiki drawing / schematic PDF.
- [ ] Module runs from 5 V on the header VBUS pin with no USB cable — schematic PDF.
- [ ] Mounting hole positions and antenna location — 2D drawing / STEP.
- [ ] Car USB goes dead at key-out — plug a phone in, remove the key.

## Build order

1. Order module, speaker, RTC cell, PN532, tags, carrier components. Hold the PCB until the checks above pass.
2. Bench: Waveshare LVGL demo → display, touch, RTC, speaker OK. PN532 on the I²C header: UIDs on screen.
3. Bench: BLE to the Vgate, speed on screen.
4. Carrier rev A to fab; same circuit on perfboard meanwhile so brownout-flush firmware isn't blocked.
5. Assemble carrier, measure hold-up (target ≥ 8 s backlight off), install.
6. Enclosure: screen to driver, PN532 behind a marked "tap" spot, USB-C reachable.

## Rev 2b (later)

Absorb the PN532 into the carrier: HVQFN40 PN532 or MFRC522, 27.12 MHz crystal, EMC filter + matching network, 3–4-turn ~40 × 40 mm printed loop per NXP AN11019 / AN1445. Needs a NanoVNA to tune to 13.56 MHz. Only worth it once Rev 2 works.

## Firmware impact

Rev 1 firmware plan stands (PlatformIO + ESP-IDF, components `obd`, `rfid`, `clock`, `store`, `sync`, `ui`, `power`). Changes:
- `rfid`: PN532 over I²C (`driver/i2c_master`), IRQ on IO18, instead of RC522/SPI.
- `clock`: PCF85063 instead of DS3231.
- `ui`: LVGL 9 on ST7789 + CST328 (Waveshare's example BSP) instead of WS2812. Backlight PWM on GPIO 5; brownout handler turns it off first.
- `power`: sense on IO15.
- Audio: short beeps via I²S → PCM5101 → speaker.
