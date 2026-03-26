# `lcd_pcf2119x` — API Reference

MicroPython driver for character LCD displays based on the NXP **PCF2119x**
controller, communicating over I²C.  
Ported from the Arduino library by José Luis Zabalza
([jlz3008/LCDi2c_PCF2119x](https://github.com/jlz3008/LCDi2c_PCF2119x)).  
Target platform: **Espressif ESP32-C3** running MicroPython.

---

## Table of contents

1. [Background — charset variants](#1-background--charset-variants)
2. [Character encoding for swapped variants](#2-character-encoding-for-swapped-variants)
3. [I²C protocol](#3-i²c-protocol)
4. [DDRAM memory map](#4-ddram-memory-map)
5. [Wiring](#5-wiring)
6. [Module-level convenience function — `make_lcd()`](#6-module-level-convenience-function--make_lcd)
7. [Class `LCD_PCF2119x`](#7-class-lcd_pcf2119x)
   - [Constructor](#constructor)
   - [Initialisation](#initialisation)
   - [Clearing and homing](#clearing-and-homing)
   - [Display on / off](#display-on--off)
   - [Cursor visibility and blink](#cursor-visibility-and-blink)
   - [Writing characters](#writing-characters)
   - [Cursor and text direction](#cursor-and-text-direction)
   - [Display scrolling](#display-scrolling)
   - [Custom characters (CGRAM)](#custom-characters-cgram)
   - [Hardware orientation — PCF2119x-specific](#hardware-orientation--pcf2119x-specific)
   - [Low-level address access — PCF2119x-specific](#low-level-address-access--pcf2119x-specific)

---

## 1. Background — charset variants

The `x` in *PCF2119x* is the ROM variant installed at manufacture. Six variants
exist, identified by the suffix letter of the part number. They use an identical
instruction set; only the glyph positions in the 256-entry character ROM differ.

| Variant | Part number | Encoding | Notes |
|---------|-------------|----------|-------|
| `'A'` | PCF2119AU | Direct | Standard Latin; straight ASCII mapping |
| `'D'` | PCF2119DU | Direct | Latin with some extensions |
| `'I'` | PCF2119IU | Direct | Similar to A / D |
| `'F'` | PCF2119FU | **Swapped** | French / Latin; `0x20–0x7F ↔ 0xA0–0xFF` |
| `'R'` | PCF2119RU | **Swapped** | Most common surplus variant; `0x20–0x7F ↔ 0xA0–0xFF` |
| `'S'` | PCF2119SU | **Swapped** | `0x20–0x7F ↔ 0xA0–0xFF` |

The `'R'` variant was produced in large quantities for fax machines and printers
and is the one most commonly encountered on the hobbyist / surplus market. It is
the **default charset** in this driver.

---

## 2. Character encoding for swapped variants

For variants **F, R, S** the printable ASCII glyphs occupy ROM positions
`0xA0–0xFF`, not `0x20–0x7F`. Space (`0x20` in ASCII) is therefore at `0xA0`
in the ROM.

The driver's internal `_ascii_to_lcd()` method applies the following
bidirectional swap automatically whenever `print()` or `write()` is called:

| Input to driver | Sent to display | Reason |
|-----------------|-----------------|--------|
| `0x00–0x1F` | unchanged | CGRAM user chars 0–15 / control codes |
| `0x20–0x7F` | `value + 0x80` → `0xA0–0xFF` | Printable ASCII → correct ROM glyph |
| `0x80–0x9F` | unchanged | CGRAM user chars 16–31 |
| `0xA0–0xFF` | `value − 0x80` → `0x20–0x7F` | Explicit access to lower ROM half |

For direct variants **A, D, I** all values pass through unchanged.

Use [`data()`](#writing-characters) to write a raw ROM code that bypasses this
translation entirely.

### Effect on `clear()` and scroll methods

The hardware `Clear_display` command fills DDRAM with `0x20`, which is **not** a
space on swapped ROMs. Therefore:

- **`clear()`** for swapped variants performs a manual DDRAM fill with `0xA0`
  (the correct space), with the display briefly turned off as required by the
  PCF2119x datasheet.
- **`scroll_display_left()` / `scroll_display_right()`** use the hardware shift
  command, which fills vacated columns with `0x20`, causing stray glyphs on
  swapped ROMs. Prefer the `_safe` variants documented below.

---

## 3. I²C protocol

Every I²C write to the PCF2119x begins with a **control byte**:

| Control byte | Meaning |
|---|---|
| `0x00` | Following bytes are **commands** (Instruction Register) |
| `0x40` | Following bytes are **data** (Data Register → DDRAM / CGRAM) |
| `0x80` | This is a control byte **and** another control byte follows the next payload byte (used to interleave a command with a data burst in a single transaction) |

Multiple commands may follow a single `0x00` in one transaction.  
Multiple data bytes may follow a single `0x40` in one transaction.  
The PCF2119x I²C buffer is limited to approximately **32 bytes per transaction**.

---

## 4. DDRAM memory map

The PCF2119x exposes 80 bytes of DDRAM as a single linear buffer:

```
Address     Content
0x00–0x0F   Visible row 0, columns 0–15
0x10–0x1F   Visible row 1, columns 0–15
0x20–0x4F   Off-screen buffer (used by hardware scroll / shift)
```

`set_cursor(col, row)` maps to DDRAM address `0x10 × row + col`.

---

## 5. Wiring

Default soft-I²C pins as used by `make_lcd()`:

| LCD pin | ESP32-C3 GPIO | Notes |
|---------|---------------|-------|
| SDA | GPIO 8 | 4.7 kΩ pull-up to 3V3 required |
| SCL | GPIO 9 | 4.7 kΩ pull-up to 3V3 required |
| VCC | 3V3 or 5 V | Check your specific panel |
| GND | GND | |
| SA0 | GND | Sets I²C address to `0x3A`; connect to VCC for `0x3B` |

Confirm the address before connecting:

```python
from machine import SoftI2C, Pin
i2c = SoftI2C(scl=Pin(9), sda=Pin(8), freq=100_000)
print([hex(a) for a in i2c.scan()])
```

---

## 6. Module-level convenience function — `make_lcd()`

```python
make_lcd(sda_pin=8, scl_pin=9, freq=100_000,
         i2c_addr=0x3A, cols=16, rows=2, charset='R')
```

Constructs a `SoftI2C` bus, instantiates `LCD_PCF2119x`, calls `begin()`, and
returns the ready-to-use object. All parameters are optional.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sda_pin` | `8` | GPIO number for SDA |
| `scl_pin` | `9` | GPIO number for SCL |
| `freq` | `100_000` | I²C bus frequency in Hz |
| `i2c_addr` | `0x3A` | 7-bit I²C address |
| `cols` | `16` | Visible columns |
| `rows` | `2` | Visible rows |
| `charset` | `'R'` | ROM variant letter (see [§1](#1-background--charset-variants)) |

**Returns** a fully initialised `LCD_PCF2119x` instance.

```python
from lcd_pcf2119x import make_lcd

lcd = make_lcd(sda_pin=8, scl_pin=9, i2c_addr=0x3A, cols=16, rows=2)
lcd.print("Ready!")
```

---

## 7. Class `LCD_PCF2119x`

### Constructor

```python
LCD_PCF2119x(i2c, i2c_addr=0x3A, cols=16, rows=2, charset='R')
```

Creates a driver instance. Does **not** send any I²C traffic — call
`begin()` to initialise the hardware.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `i2c` | `machine.I2C` or `SoftI2C` | — | Pre-constructed I²C bus object |
| `i2c_addr` | `int` | `0x3A` | 7-bit I²C address (`0x3A` when SA0=GND, `0x3B` when SA0=VCC) |
| `cols` | `int` | `16` | Number of visible columns |
| `rows` | `int` | `2` | Number of visible rows |
| `charset` | `str` | `'R'` | ROM variant: `'A'`, `'D'`, `'I'` (direct) or `'F'`, `'R'`, `'S'` (swapped) |

Raises `ValueError` for an unrecognised `charset` letter.

```python
from machine import SoftI2C, Pin
from lcd_pcf2119x import LCD_PCF2119x

i2c = SoftI2C(scl=Pin(9), sda=Pin(8), freq=100_000)
lcd = LCD_PCF2119x(i2c, i2c_addr=0x3A, cols=16, rows=2, charset='R')
lcd.begin()
```

---

### Initialisation

#### `begin(cols=None, rows=None)`

Sends the full hardware initialisation sequence and clears the display.
Optionally overrides the `cols` / `rows` set in the constructor.

The sequence configures (in a single I²C transaction): Function set, Entry
mode, Cursor shift, `Disp_conf`, `Temp_ctl`, `HV_gen`, `VLCDset`, and
Return home. The `Temp_ctl` (`0x10`), `HV_gen` (`0x42`), and `VLCDset`
(`0x9F`) values are tuned for BT21605 / PCF2119RU panels; edit them in
`_init_display()` for panels requiring different voltage or temperature
compensation.

```python
lcd.begin()           # use cols/rows from constructor
lcd.begin(20, 4)      # override to a 20×4 display
```

---

### Clearing and homing

#### `clear()`

Clear all characters from the display and return the cursor to (0, 0).

- **Direct charsets (A, D, I):** issues the hardware `Clear_display` command.
- **Swapped charsets (F, R, S):** performs a manual DDRAM fill with `0xA0`
  (the space glyph on these ROMs) across all 80 addresses, with the display
  blanked during the write.

#### `home()`

Return the cursor to position (0, 0) without modifying DDRAM content.

---

### Display on / off

#### `display()`

Turn the display on. Characters stored in DDRAM become visible.

#### `no_display()`

Turn the display off. DDRAM content is preserved and restored when `display()`
is called.

---

### Cursor visibility and blink

#### `cursor()`

Show the underline cursor at the current cursor position.

#### `no_cursor()`

Hide the underline cursor. Default state.

#### `blink()`

Enable the blinking-block cursor. Can be active simultaneously with the
underline cursor.

#### `no_blink()`

Disable the blinking-block cursor. Default state.

---

### Writing characters

#### `print(text)`

Write a string to DDRAM at the current cursor position. Each character is
translated through the charset mapping before being sent. The cursor advances
automatically according to the current text direction.

```python
lcd.print("Hello, world!")
```

#### `write(value)`

Write a single character given as an integer codepoint, with charset
translation applied.

```python
lcd.write(ord('A'))
lcd.write(0)      # CGRAM slot 0 (user-defined character)
```

#### `data(value)`

Write a raw byte to DDRAM **without** charset translation. Use this to address
a specific ROM glyph position directly, or to emit a CGRAM user character by
slot number in an unambiguous way.

```python
lcd.data(0x00)    # CGRAM slot 0, no translation
lcd.data(0xA8)    # ROM position 0xA8 directly
```

> On swapped variants the swap does **not** apply to `0x00–0x1F`, so
> `write(n)` and `data(n)` are equivalent for `n` in `0–15`.

---

### Cursor and text direction

#### `set_cursor(col, row)`

Move the cursor to column `col`, row `row` (both 0-indexed). Subsequent write
calls start from this position. DDRAM address = `0x10 × row + col`.

```python
lcd.set_cursor(0, 1)    # beginning of row 1
lcd.set_cursor(8, 0)    # column 8 of row 0
```

#### `cursor_left()`

Move the cursor one position to the left without shifting the display.

#### `cursor_right()`

Move the cursor one position to the right without shifting the display.

#### `left_to_right()`

Set text direction left-to-right: DDRAM address increments after each write.
This is the default.

#### `right_to_left()`

Set text direction right-to-left: DDRAM address decrements after each write.

---

### Display scrolling

All scroll methods shift the **visible window** over the 80-byte DDRAM buffer.
DDRAM content is not modified; only the internal display address offset changes.

#### `autoscroll()`

Enable autoscroll: the display shifts left on each character write so that new
characters appear to stay at the cursor position.

> ⚠️ **Swapped charsets (F, R, S):** the hardware fills vacated columns with
> `0x20`, which is not a space on these ROMs. Stray glyphs appear at the right
> edge.

#### `no_autoscroll()`

Disable autoscroll. Default state.

#### `scroll_display_left()`

Shift the visible window one position to the left using the hardware
`Curs_disp_shift` command (`0x18`).

> ⚠️ **Swapped charsets (F, R, S):** the hardware fills the newly revealed
> right column with `0x20`. Use `scroll_display_left_safe()` instead.

#### `scroll_display_right()`

Shift the visible window one position to the right (`0x1C`).

> ⚠️ **Swapped charsets (F, R, S):** fills the newly revealed left column with
> `0x20`. Use `scroll_display_right_safe()` instead.

#### `scroll_display_left_safe()`

Shift the visible window one position to the left with correct blank-fill.

For **swapped charsets**: pre-writes `0xA0` (the correct space glyph) into the
off-screen column about to be revealed, then issues the hardware shift.  
For **direct charsets**: identical to `scroll_display_left()`.

#### `scroll_display_right_safe()`

Shift the visible window one position to the right with correct blank-fill.

For **swapped charsets**: pre-writes `0xA0` into the off-screen column about
to be revealed, then issues the hardware shift.  
For **direct charsets**: identical to `scroll_display_right()`.

---

### Custom characters (CGRAM)

#### `create_char(char_num, rows_data)`

Define a custom 5×8 glyph in CGRAM.

| Parameter | Type | Description |
|-----------|------|-------------|
| `char_num` | `int` (0–15) | CGRAM slot. Slots 0–3 are shared with the icon feature; avoid them if icons are active. |
| `rows_data` | iterable of 8 `int`s | Pixel rows top-to-bottom. Each value is 5 bits wide (bits 4–0); bits 7–5 are ignored. |

To display a custom character after defining it, call `data(char_num)` or
`write(char_num)` with a value of `0–15`. The charset swap does not apply to
this range so both methods work identically regardless of charset.

```python
heart = [
    0b00000,
    0b01010,
    0b11111,
    0b11111,
    0b01110,
    0b00100,
    0b00000,
    0b00000,
]
lcd.create_char(0, heart)
lcd.set_cursor(0, 0)
lcd.data(0)             # display the heart glyph
```

> **PCF2119x CGRAM addressing note:** The `Set_CGRAM` command can only set
> bits 5–0 of the address. Bit 6 must be primed via a `Set_DDRAM` command.
> Slots 8–15 therefore require an extra command, which the driver handles
> automatically.

---

### Hardware orientation — PCF2119x-specific

These methods write to the PCF2119x extended-instruction-set `Disp_conf`
register, which controls the hardware scan direction of the row and column
drivers. Useful when the module is physically mounted rotated 180°.

#### `normal_horizontal_orientation()`

Left-to-right column scan order. Default state.

#### `reverse_horizontal_orientation()`

Right-to-left column scan order (mirrors the display horizontally).

#### `normal_vertical_orientation()`

Top-to-bottom row scan order. Default state.

#### `reverse_vertical_orientation()`

Bottom-to-top row scan order (flips the display vertically).

---

### Low-level address access — PCF2119x-specific

#### `get_address_point()`

Read the current DDRAM or CGRAM address counter from the controller. Returns
the 7-bit address as an integer (the busy flag in bit 7 is masked out).

```python
addr = lcd.get_address_point()
```

#### `set_address_point(new_addr)`

Set the DDRAM address pointer directly (valid range `0x00–0x4F`). Equivalent
to `set_cursor()` but takes a raw DDRAM address rather than col / row
coordinates.

```python
lcd.set_address_point(0x10)   # same effect as lcd.set_cursor(0, 1)
```

---

*Driver source: `lcd_pcf2119x.py` — LGPLv3+*
