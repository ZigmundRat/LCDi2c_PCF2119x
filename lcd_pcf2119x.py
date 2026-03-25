"""
lcd_pcf2119x.py  –  MicroPython driver for PCF2119x-based I²C LCD displays
===========================================================================
Ported from the Arduino library by José Luis Zabalza (jlz3008/LCDi2c_PCF2119x)
Original licence: LGPLv3+

Target: MicroPython on Espressif ESP32-C3 (machine.I2C / machine.SoftI2C)

Typical wiring (ESP32-C3 default soft-I²C pins):
  SDA  → GPIO 8
  SCL  → GPIO 9
  VCC  → 3V3  (some modules: 5 V – check your panel)
  GND  → GND

Quick-start
-----------
    from machine import SoftI2C, Pin
    from lcd_pcf2119x import LCD_PCF2119x

    i2c = SoftI2C(scl=Pin(9), sda=Pin(8), freq=100_000)
    lcd = LCD_PCF2119x(i2c, i2c_addr=0x3A, cols=16, rows=2, charset='E')
    lcd.begin()
    lcd.print("Hello, world!")
    lcd.set_cursor(0, 1)
    lcd.print("ESP32-C3  :)")

Charset codes (match the PCF2119x ROM variant suffix)
------------------------------------------------------
  'E'  European   (default; standard Latin / ASCII mapping)
  'S'  Cyrillic   (requires special clear sequence; remapped characters)
  'F'  French     (remapped characters similar to 'R')
  'R'  European?  (remapped characters - PITA)

The PCF2119x stores 80 characters in DDRAM arranged as one logical row
of 80 bytes.  A 2×16 physical display shows bytes [0..15] on line 0 and
[16..31] on line 1, but byte positions 32..79 exist and are used by the
hardware autoscroll/shift feature.

I²C protocol (PCF2119x)
------------------------
Every I²C write begins with a *control byte*:
  0x00  → following bytes are commands  (Instruction Register)
  0x40  → following bytes are data      (Data Register)
  0x80  → this byte is a control byte, and the *next* byte is also
           followed by another control byte (used for mixed sequences)

The driver mirrors the original C++ API as closely as practical while
adapting to Python conventions (snake_case names, no size_t return, etc.).
"""

import time
from micropython import const

# ---------------------------------------------------------------------------
# PCF2119x command constants
# ---------------------------------------------------------------------------
_CMD_CLEAR_DISPLAY   = const(0x01)
_CMD_RETURN_HOME     = const(0x02)
_CMD_ENTRY_MODE      = const(0x04)   # base: OR in flags below
_CMD_DISPLAY_CTRL    = const(0x08)   # base: OR in flags below
_CMD_SHIFT           = const(0x10)   # base: OR in flags below
_CMD_FUNCTION_BASIC  = const(0x30)   # Function set – basic instruction set
_CMD_FUNCTION_EXT    = const(0x31)   # Function set – extended instruction set
_CMD_SET_CGRAM       = const(0x40)   # OR in 6-bit address
_CMD_SET_DDRAM       = const(0x80)   # OR in 7-bit address

# Entry-mode flags
_ENTRY_INC           = const(0x02)   # address increment (left-to-right)
_ENTRY_DEC           = const(0x00)   # address decrement (right-to-left)
_ENTRY_SHIFT         = const(0x01)   # display shift on write (autoscroll)
_ENTRY_NO_SHIFT      = const(0x00)

# Display-control flags
_DISP_ON             = const(0x04)
_DISP_OFF            = const(0x00)
_CURSOR_ON           = const(0x02)
_CURSOR_OFF          = const(0x00)
_BLINK_ON            = const(0x01)
_BLINK_OFF           = const(0x00)

# Shift command flags
_SHIFT_DISPLAY       = const(0x08)   # shift display (not cursor)
_SHIFT_RIGHT         = const(0x04)   # shift / move right

# Extended-instruction display-config flags
_DISP_CONF_BASE      = const(0x04)
_H_NORMAL            = const(0x00)
_H_REVERSE           = const(0x02)
_V_NORMAL            = const(0x00)
_V_REVERSE           = const(0x01)

# I²C control bytes
_CTRL_CMD            = const(0x00)   # next byte(s) → IR
_CTRL_DATA           = const(0x40)   # next byte(s) → DR
_CTRL_CONTINUED      = const(0x80)   # control byte follows the next byte

# Busy-flag mask (bit 7 of IR read)
_BUSY_FLAG           = const(0x80)
_MAX_RETRY           = const(10)

# Blank/white character for charset 'R' clear
_BLANK_R             = const(0x91)
_BLANK_STD           = const(0x20)   # ASCII space


class LCD_PCF2119x:
    """
    MicroPython driver for PCF2119x I²C character LCD.

    Parameters
    ----------
    i2c       : machine.I2C or machine.SoftI2C instance (already constructed)
    i2c_addr  : 7-bit I²C address of the display (commonly 0x3A or 0x3B)
    cols      : number of visible columns (e.g. 16)
    rows      : number of visible rows    (e.g. 2)
    charset   : PCF2119x ROM variant: 'E' (European), 'R' (Cyrillic), 'F' (French)
    """

    def __init__(self, i2c, i2c_addr=0x3A, cols=16, rows=2, charset='E'):
        self._i2c     = i2c
        self._addr    = i2c_addr
        self._cols    = cols
        self._rows    = rows
        self._charset = charset.upper()

        # State mirrors
        self._blink    = _BLINK_OFF
        self._cursor   = _CURSOR_OFF
        self._active   = _DISP_ON
        self._h_orient = _H_NORMAL
        self._v_orient = _V_NORMAL
        self._scroll   = _ENTRY_NO_SHIFT
        self._dir      = _ENTRY_INC

    # ------------------------------------------------------------------
    # Public API  (compatible with LiquidCrystal_I2C / LCD API 1.0)
    # ------------------------------------------------------------------

    def begin(self, cols=None, rows=None):
        """Initialise the display.  Optionally override cols/rows set in __init__."""
        if cols is not None:
            self._cols = cols
        if rows is not None:
            self._rows = rows
        self._init_display()

    def clear(self):
        """Clear all characters from the display and return cursor to home."""
        if self._charset == 'R':
            self._clear_cyrillic()
        else:
            self._command(_CMD_CLEAR_DISPLAY)

    def home(self):
        """Return cursor to position (0, 0) without clearing."""
        self._command(_CMD_RETURN_HOME)

    def display(self):
        """Turn the display on (characters visible)."""
        self._active = _DISP_ON
        self._set_display_control()

    def no_display(self):
        """Turn the display off (characters retained in DDRAM)."""
        self._active = _DISP_OFF
        self._set_display_control()

    def cursor(self):
        """Show the underline cursor."""
        self._cursor = _CURSOR_ON
        self._set_display_control()

    def no_cursor(self):
        """Hide the underline cursor."""
        self._cursor = _CURSOR_OFF
        self._set_display_control()

    def blink(self):
        """Enable blinking-block cursor."""
        self._blink = _BLINK_ON
        self._set_display_control()

    def no_blink(self):
        """Disable blinking-block cursor."""
        self._blink = _BLINK_OFF
        self._set_display_control()

    def set_cursor(self, col, row):
        """
        Move cursor to (col, row).  Both are 0-indexed.
        DDRAM address = 0x10 * row + col  (16 bytes per logical row).
        """
        addr = 0x10 * row + col
        self._command(_CMD_SET_DDRAM | (addr & 0x7F))

    def print(self, text):
        """Write a string to the display at the current cursor position."""
        for ch in text:
            self._write_char(ord(ch))

    def write(self, value):
        """Write a single character code (int) to the display."""
        self._write_char(value)

    def autoscroll(self):
        """Enable autoscroll: display shifts on each character write."""
        self._scroll = _ENTRY_SHIFT
        self._set_entry_mode()

    def no_autoscroll(self):
        """Disable autoscroll."""
        self._scroll = _ENTRY_NO_SHIFT
        self._set_entry_mode()

    def left_to_right(self):
        """Set text direction left-to-right (address increment)."""
        self._dir = _ENTRY_INC
        self._set_entry_mode()

    def right_to_left(self):
        """Set text direction right-to-left (address decrement)."""
        self._dir = _ENTRY_DEC
        self._set_entry_mode()

    def scroll_display_left(self):
        """Shift the visible window one position to the left."""
        self._command(_CMD_SHIFT | _SHIFT_DISPLAY | 0x00)  # 0x18

    def scroll_display_right(self):
        """Shift the visible window one position to the right."""
        self._command(_CMD_SHIFT | _SHIFT_DISPLAY | _SHIFT_RIGHT)  # 0x1C

    def cursor_left(self):
        """Move cursor one position to the left."""
        self._command(_CMD_SHIFT | 0x00)  # 0x10

    def cursor_right(self):
        """Move cursor one position to the right."""
        self._command(_CMD_SHIFT | _SHIFT_RIGHT)  # 0x14

    def create_char(self, char_num, rows_data):
        """
        Define a custom character in CGRAM.

        Parameters
        ----------
        char_num  : slot 0-15 (PCF2119x supports 16 custom chars)
        rows_data : sequence of 8 bytes (5-bit pixel rows, MSB ignored)
        """
        char_num &= 0x0F
        cgram_addr = char_num * 8

        buf = bytearray()
        # If char_num >= 8 bit6 must be set via the DDRAM mechanism first
        if char_num >= 8:
            buf += bytes([_CTRL_CONTINUED,
                          _CMD_SET_DDRAM | (cgram_addr & 0xFF)])  # sets bit6
        buf += bytes([_CTRL_CMD,
                      _CMD_SET_CGRAM | (cgram_addr & 0x3F)])
        self._i2c.writeto(self._addr, buf)
        self._wait_busy()

        data_buf = bytearray([_CTRL_DATA] + list(rows_data[:8]))
        self._i2c.writeto(self._addr, data_buf)
        self._wait_busy()

    # ------------------------------------------------------------------
    # PCF2119x-specific extensions
    # ------------------------------------------------------------------

    def normal_horizontal_orientation(self):
        """Display left-to-right (default)."""
        self._h_orient = _H_NORMAL
        self._set_display_config()

    def reverse_horizontal_orientation(self):
        """Mirror display horizontally."""
        self._h_orient = _H_REVERSE
        self._set_display_config()

    def normal_vertical_orientation(self):
        """Display top-to-bottom (default)."""
        self._v_orient = _V_NORMAL
        self._set_display_config()

    def reverse_vertical_orientation(self):
        """Flip display vertically."""
        self._v_orient = _V_REVERSE
        self._set_display_config()

    def get_address_point(self):
        """Read the current DDRAM/CGRAM address pointer from the controller."""
        self._i2c.writeto(self._addr, bytes([_CTRL_CMD]))
        data = self._i2c.readfrom(self._addr, 1)
        return data[0] & 0x7F

    def set_address_point(self, new_addr):
        """Directly set the DDRAM address pointer."""
        self._command(_CMD_SET_DDRAM | (new_addr & 0x7F))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _command(self, value):
        self._i2c.writeto(self._addr, bytes([_CTRL_CMD, value]))
        self._wait_busy()

    def _write_char(self, value):
        self._i2c.writeto(self._addr, bytes([_CTRL_DATA, self._ascii_to_lcd(value)]))
        self._wait_busy()

    def _wait_busy(self, max_retry=_MAX_RETRY):
        """Poll the busy flag (bit 7 of IR) until clear or timeout."""
        self._i2c.writeto(self._addr, bytes([_CTRL_CMD]))
        for _ in range(max_retry):
            data = self._i2c.readfrom(self._addr, 1)
            if not (data[0] & _BUSY_FLAG):
                return
            # Small yield – avoids tight-spinning; I²C at 100 kHz is already slow
            time.sleep_us(50)

    def _set_display_control(self):
        self._command(_CMD_DISPLAY_CTRL | self._active | self._cursor | self._blink)

    def _set_entry_mode(self):
        self._command(_CMD_ENTRY_MODE | self._scroll | self._dir)

    def _set_display_config(self):
        """Switch to extended instruction set, set Disp_conf, return to basic set."""
        self._i2c.writeto(self._addr, bytes([
            _CTRL_CMD,
            _CMD_FUNCTION_EXT,                                        # extended IS
            _DISP_CONF_BASE | self._h_orient | self._v_orient,        # Disp_conf
            _CMD_FUNCTION_BASIC,                                      # back to basic IS
        ]))
        self._wait_busy()

    def _init_display(self):
        """
        Full hardware initialisation sequence from the original library.
        All multi-command writes are sent in a single I²C transaction.
        """
        self._i2c.writeto(self._addr, bytes([
            _CTRL_CMD,
            _CMD_FUNCTION_BASIC,                                              # basic IS
            _CMD_ENTRY_MODE  | self._dir | self._scroll,                      # entry mode
            _CMD_SHIFT       | _SHIFT_RIGHT,                                  # Curs_disp_shift right
            _CMD_FUNCTION_EXT,                                                # extended IS
            _DISP_CONF_BASE  | self._h_orient | self._v_orient,               # Disp_conf
            0x10,                                                             # Temp_ctl  (TC1=0, TC2=0)
            0x42,                                                             # HV_gen    (3 stages)
            0x9F,                                                             # VLCDset   (store VA)
            _CMD_FUNCTION_BASIC,                                              # basic IS
            _CMD_SET_DDRAM,                                                   # DDRAM address = 0x00
            _CMD_RETURN_HOME,                                                 # return home
        ]))
        self._wait_busy()
        self.clear()
        self._set_display_control()

    def _clear_cyrillic(self):
        """
        Special clear sequence required for charset 'R' (from PCF2119x datasheet).
        The display must be turned off, all 80 DDRAM bytes written with 0x91 (blank),
        then the display is turned back on.
        """
        was_on = self._active == _DISP_ON
        self.no_display()

        # PCF2119x I²C transmissions are limited to ~32 bytes per transaction.
        # Write 80 blank bytes in three chunks:
        #   chunk 0:  addr 0x00, 27 bytes  (0x00..0x1A)
        #   chunk 1:  addr 0x1B, 27 bytes  (0x1B..0x35)
        #   chunk 2:  addr 0x36, 26 bytes  (0x36..0x4F)
        chunks = [
            (0x00, 27),
            (0x1B, 27),
            (0x36, 26),
        ]
        for start_addr, count in chunks:
            buf = bytes([
                _CTRL_CONTINUED,
                _CMD_SET_DDRAM | start_addr,
                _CTRL_DATA,
            ]) + bytes([_BLANK_R] * count)
            self._i2c.writeto(self._addr, buf)
            self._wait_busy()

        self.home()
        if was_on:
            self.display()

    def _ascii_to_lcd(self, ch):
        """
        Translate an ASCII code point to the PCF2119x character-ROM address.

        For charsets 'R' and 'F' the visible ASCII range (0x20-0x7A) must be
        offset by +0x80 to address the correct glyph in the ROM.
        Charset 'E' uses direct ASCII codes (no remapping needed for
        printable range).
        """
        if self._charset in ('R', 'F'):
            if (0x20 <= ch <= 0x3F) or (0x41 <= ch <= 0x5A) or (0x61 <= ch <= 0x7A):
                return (0x80 + ch) & 0xFF
        return ch & 0xFF


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_lcd(sda_pin=8, scl_pin=9, freq=100_000,
             i2c_addr=0x3A, cols=16, rows=2, charset='E'):
    """
    Construct a SoftI2C bus and return an initialised LCD_PCF2119x instance.

    Example
    -------
        from lcd_pcf2119x import make_lcd
        lcd = make_lcd(sda_pin=8, scl_pin=9, i2c_addr=0x3A, cols=16, rows=2)
        lcd.print("Ready!")
    """
    from machine import SoftI2C, Pin
    i2c = SoftI2C(scl=Pin(scl_pin), sda=Pin(sda_pin), freq=freq)
    lcd = LCD_PCF2119x(i2c, i2c_addr=i2c_addr, cols=cols, rows=rows, charset=charset)
    lcd.begin()
    return lcd
