"""
example_lcd.py  –  Usage examples for lcd_pcf2119x.py on ESP32-C3
==================================================================
Copy both lcd_pcf2119x.py and this file to the ESP32-C3 filesystem,
then run this script (or paste into the REPL).

Wiring (adjust pin numbers to suit your board):
  LCD SDA  →  GPIO 8
  LCD SCL  →  GPIO 9
  LCD VCC  →  3V3 (or 5 V – check your specific panel)
  LCD GND  →  GND

I²C address: most PCF2119x boards respond on 0x3A (SA0=VSS) or 0x3B (SA0=VDD).
Run i2c.scan() first if you are unsure.
"""

from machine import SoftI2C, Pin
import time
from lcd_pcf2119x import LCD_PCF2119x

# -------------------------------------------------------------------
# 1. Construct I²C bus and LCD driver
# -------------------------------------------------------------------
i2c = SoftI2C(scl=Pin(9), sda=Pin(8), freq=100_000)

# Optional: scan for I²C devices to confirm address
# print("I²C devices found:", [hex(a) for a in i2c.scan()])

lcd = LCD_PCF2119x(i2c, i2c_addr=0x3B, cols=16, rows=2, charset='R')
lcd.begin()          # sends the full PCF2119x initialisation sequence

# -------------------------------------------------------------------
# 2. Basic text output
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Hello, world!")
lcd.set_cursor(0, 1)          # column 0, row 1
lcd.print("ESP32-C3  :)")
time.sleep(2)

# -------------------------------------------------------------------
# 3. Cursor and blink
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Cursor demo")
lcd.set_cursor(0, 1)
lcd.cursor()                  # underline cursor
time.sleep(1)
lcd.blink()                   # add blinking block
time.sleep(1)
lcd.no_cursor()
lcd.no_blink()

# -------------------------------------------------------------------
# 4. Scroll the display left / right
# -------------------------------------------------------------------
lcd.clear()
lcd.print("<<< Scroll >>>" )
time.sleep(1)
for _ in range(4):
    lcd.scroll_display_left()
    time.sleep(0.2)
for _ in range(4):
    lcd.scroll_display_right()
    time.sleep(0.2)

# -------------------------------------------------------------------
# 5. Custom characters (user-defined glyphs)
# -------------------------------------------------------------------
# Define a simple heart glyph (5×8 pixels)
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
lcd.create_char(0, heart)     # store in CGRAM slot 0

lcd.clear()
lcd.print("I ")
lcd.write(0)                  # write custom char by slot number
lcd.print(" MicroPython")
time.sleep(2)

# -------------------------------------------------------------------
# 6. Display on / off
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Blink display")
for _ in range(3):
    lcd.no_display()
    time.sleep(0.4)
    lcd.display()
    time.sleep(0.4)

# -------------------------------------------------------------------
# 7. Uptime counter – runs indefinitely
# -------------------------------------------------------------------
lcd.clear()
lcd.print("Uptime:")
start = time.ticks_ms()
while True:
    elapsed = time.ticks_diff(time.ticks_ms(), start) // 1000
    lcd.set_cursor(0, 1)
    lcd.print("{:>10d} s  ".format(elapsed))
    time.sleep(1)
