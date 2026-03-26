"""
example_lcd.py  -  Usage examples for lcd_pcf2119x.py on ESP32-C3
==================================================================
Copy both lcd_pcf2119x.py and this file to the ESP32-C3 filesystem,
then run this script (or paste into the REPL).

Wiring (adjust pin numbers to suit your board):
  LCD SDA  ->  GPIO 8
  LCD SCL  ->  GPIO 9
  LCD VCC  ->  3V3 (or 5 V - check your specific panel)
  LCD GND  ->  GND

I2C address: PCF2119x responds on 0x3A (SA0=GND) or 0x3B (SA0=VCC).
Run i2c.scan() first if you are unsure.

Charset: the 'R' variant (PCF2119RU) is used below because it is the
one most commonly available on the surplus/hobbyist market.  Change to
'A', 'D', or 'I' if you have a direct-mapped variant.
"""

from machine import SoftI2C, Pin
import time
from lcd_pcf2119x import LCD_PCF2119x

# -------------------------------------------------------------------
# 1. Construct I2C bus and LCD driver
# -------------------------------------------------------------------
i2c = SoftI2C(scl=Pin(9), sda=Pin(8), freq=100_000)

# Optional: confirm I2C address
# print("I2C devices found:", [hex(a) for a in i2c.scan()])

# charset='R' -> PCF2119RU (swapped ROM, most common surplus variant)
# charset='A' -> PCF2119AU (direct ASCII mapping, no remapping needed)
lcd = LCD_PCF2119x(i2c, i2c_addr=0x3A, cols=16, rows=2, charset='R')
lcd.begin()   # sends full PCF2119x init sequence, then clears with 0xA0

# -------------------------------------------------------------------
# 2. Basic text output
# -------------------------------------------------------------------
# clear() for charset 'R' fills DDRAM with 0xA0 (not 0x20) so the
# display shows true blank cells.
lcd.clear()
lcd.print("Hello, world!")
lcd.set_cursor(0, 1)       # col 0, row 1
lcd.print("ESP32-C3  :)")
time.sleep(2)

# -------------------------------------------------------------------
# 3. Cursor and blink
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Cursor demo")
lcd.set_cursor(0, 1)
lcd.cursor()               # underline
time.sleep(1)
lcd.blink()                # add blinking block
time.sleep(1)
lcd.no_cursor()
lcd.no_blink()

# -------------------------------------------------------------------
# 4. Safe scroll (use *_safe variants on swapped-charset ROMs)
# -------------------------------------------------------------------
lcd.clear()
lcd.print("<<< Scroll >>>")
time.sleep(1)
for _ in range(4):
    lcd.scroll_display_left_safe()    # pre-fills revealed col with 0xA0
    time.sleep(0.2)
for _ in range(4):
    lcd.scroll_display_right_safe()   # pre-fills revealed col with 0xA0
    time.sleep(0.2)

# -------------------------------------------------------------------
# 5. Custom characters
# -------------------------------------------------------------------
# Define a heart glyph in CGRAM slot 0
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

lcd.clear()
lcd.print("I ")
# User-defined chars live at ROM positions 0x00-0x0F regardless of
# charset. Use data() to write the slot number without translation.
lcd.data(0)                # CGRAM slot 0 -> heart glyph
lcd.print(" MicroPython")
time.sleep(2)

# -------------------------------------------------------------------
# 6. Raw ROM access via data()
# -------------------------------------------------------------------
# data() bypasses _ascii_to_lcd() and writes directly to DDRAM.
# Useful when you know the exact ROM position you want.
lcd.clear()
lcd.print("Raw ROM bytes:")
lcd.set_cursor(0, 1)
# On the R ROM, 0xA0-0xFF is where printable ASCII lives.
# Writing 0xA0 + n directly gives the same result as print(chr(0x20+n))
# but this makes the mapping explicit.
for code in (0xA8, 0xA5, 0xAC, 0xAC, 0xAF):  # H E L L O in R-ROM
    lcd.data(code)
time.sleep(2)

# -------------------------------------------------------------------
# 7. Display on/off blink
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Blink display")
for _ in range(3):
    lcd.no_display()
    time.sleep(0.4)
    lcd.display()
    time.sleep(0.4)

# -------------------------------------------------------------------
# 8. Uptime counter - runs indefinitely
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Uptime:")
start = time.ticks_ms()
while True:
    elapsed = time.ticks_diff(time.ticks_ms(), start) // 1000
    lcd.set_cursor(0, 1)
    lcd.print("{:>10d} s  ".format(elapsed))
    time.sleep(1)
