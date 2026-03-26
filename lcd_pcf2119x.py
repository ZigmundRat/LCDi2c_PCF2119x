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
    lcd = LCD_PCF2119x(i2c, i2c_addr=0x3A, cols=16, rows=2, charset='R')
    lcd.begin()
    lcd.print("Hello, world!")
    lcd.set_cursor(0, 1)
    lcd.print("ESP32-C3  :)")

PCF2119x charset variants (the suffix letter in the part number)
----------------------------------------------------------------
The 'x' in PCF2119x is the ROM variant fitted at manufacture.  Six variants
exist; they differ only in which glyphs are stored and how the 256 character
ROM positions are laid out relative to ASCII:

  Variant  Part number   Encoding      Notes
  -------  -----------   --------      -----
  'A'      PCF2119AU     direct        Standard Latin; no remapping needed
  'D'      PCF2119DU     direct        Latin + some extensions
  'I'      PCF2119IU     direct        Similar to A/D
  'F'      PCF2119FU     swapped       French/Latin; 0x20-0x7F <-> 0xA0-0xFF
  'R'      PCF2119RU     swapped       Widely sold surplus; 0x20-0x7F <-> 0xA0-0xFF
  'S'      PCF2119SU     swapped       0x20-0x7F <-> 0xA0-0xFF

The 'R' variant is the one most commonly encountered on the surplus/hobbyist
market (produced in large quantities for fax machines and printers).

CHARACTER ENCODING FOR SWAPPED VARIANTS (F, R, S)
--------------------------------------------------
The glyph that looks like an ASCII space is NOT at code 0x20 in the ROM.
The entire printable ASCII block (0x20-0x7F) is physically located at
0xA0-0xFF in the ROM, and vice versa.  The driver applies the following
bidirectional swap transparently in _ascii_to_lcd():

  Input value    Sent to display   Reason
  -----------    ---------------   ------
  0x00-0x1F      unchanged         CGRAM user chars 0-15 / control codes
  0x20-0x7F      value + 0x80      printable ASCII -> ROM glyphs at 0xA0-0xFF
  0x80-0x9F      unchanged         CGRAM user chars 16-31 (if used)
  0xA0-0xFF      value - 0x80      access lower ROM half if needed explicitly

Use data() to write a raw ROM code bypassing this translation entirely.

CONSEQUENCE FOR clear() AND scroll ON F/R/S
-------------------------------------------
The hardware Clear_display command (0x01) fills DDRAM with 0x20, which is
NOT a space on F/R/S ROMs.  Therefore clear() performs a manual DDRAM fill
with 0xA0 (the correct space after the +0x80 swap) for these variants, with
the display blanked during the write as required by the datasheet.

Similarly, scroll_display_left() and scroll_display_right() call the hardware
Curs_disp_shift command which fills vacated positions with 0x20, producing
visible glyph artefacts on F/R/S.  These methods still work but carry a
docstring warning.  Use scroll_display_left_safe() / scroll_display_right_safe()
which pre-fill the revealed column with 0xA0 before shifting.

I2C PROTOCOL (PCF2119x)
------------------------
Every I2C write begins with a control byte:
  0x00  -> following bytes are commands  (Instruction Register, IR)
  0x40  -> following bytes are data      (Data Register, DR)
  0x80  -> this byte is a control byte, AND the next payload byte is itself
           followed by another control byte (used for mixed IR/DR sequences)

Multiple commands may follow a single 0x00 control byte in one transaction.
Multiple data bytes may follow a single 0x40 control byte in one transaction.
"""

import time
from micropython import const

# ---------------------------------------------------------------------------
# PCF2119x command constants
# ---------------------------------------------------------------------------
_CMD_CLEAR_DISPLAY  = const(0x01)
_CMD_RETURN_HOME    = const(0x02)
_CMD_ENTRY_MODE     = const(0x04)   # base; OR in entry-mode flags
_CMD_DISPLAY_CTRL   = const(0x08)   # base; OR in display-control flags
_CMD_SHIFT          = const(0x10)   # base; OR in shift flags
_CMD_FUNCTION_BASIC = const(0x30)   # Function set - basic instruction set
_CMD_FUNCTION_EXT   = const(0x31)   # Function set - extended instruction set
_CMD_SET_CGRAM      = const(0x40)   # OR in 6-bit CGRAM address
_CMD_SET_DDRAM      = const(0x80)   # OR in 7-bit DDRAM address

# Entry-mode flags (ORed into _CMD_ENTRY_MODE)
_ENTRY_INC          = const(0x02)   # address increment  -> left-to-right
_ENTRY_DEC          = const(0x00)   # address decrement  -> right-to-left
_ENTRY_SHIFT        = const(0x01)   # display shift on each write (autoscroll)
_ENTRY_NO_SHIFT     = const(0x00)

# Display-control flags (ORed into _CMD_DISPLAY_CTRL)
_DISP_ON            = const(0x04)
_DISP_OFF           = const(0x00)
_CURSOR_ON          = const(0x02)
_CURSOR_OFF         = const(0x00)
_BLINK_ON           = const(0x01)
_BLINK_OFF          = const(0x00)

# Shift command flags (ORed into _CMD_SHIFT)
_SHIFT_DISPLAY      = const(0x08)   # operate on display (not cursor)
_SHIFT_RIGHT        = const(0x04)   # direction: right

# Extended-instruction Disp_conf flags
_DISP_CONF_BASE     = const(0x04)
_H_NORMAL           = const(0x00)
_H_REVERSE          = const(0x02)
_V_NORMAL           = const(0x00)
_V_REVERSE          = const(0x01)

# I2C control bytes
_CTRL_CMD           = const(0x00)   # next byte(s) -> IR
_CTRL_DATA          = const(0x40)   # next byte(s) -> DR
_CTRL_CONTINUED     = const(0x80)   # this byte is a control byte; another follows

# Busy-flag
_BUSY_FLAG          = const(0x80)   # bit 7 of IR readback
_MAX_RETRY          = const(10)

# Blank character values for manual DDRAM clear:
#   direct  (A, D, I): 0x20 = ASCII space (same as hardware clear)
#   swapped (F, R, S): 0xA0 = ROM address of the space glyph after +0x80 swap
_BLANK_DIRECT       = const(0x20)
_BLANK_SWAPPED      = const(0xA0)

# Valid charset letters
_CHARSETS_DIRECT    = ('A', 'D', 'I')
_CHARSETS_SWAPPED   = ('F', 'R', 'S')


class LCD_PCF2119x:
    """
    MicroPython driver for PCF2119x I2C character LCD.

    Parameters
    ----------
    i2c      : machine.I2C or machine.SoftI2C instance (already constructed)
    i2c_addr : 7-bit I2C address (0x3A when SA0=GND, 0x3B when SA0=VCC)
    cols     : number of visible columns (e.g. 16)
    rows     : number of visible rows    (e.g. 2)
    charset  : PCF2119x ROM variant letter: 'A', 'D', 'I' (direct) or
               'F', 'R', 'S' (swapped).  Default 'R' matches the most
               commonly available surplus module (PCF2119RU).
    """

    def __init__(self, i2c, i2c_addr=0x3A, cols=16, rows=2, charset='R'):
        self._i2c  = i2c
        self._addr = i2c_addr
        self._cols = cols
        self._rows = rows

        cs = charset.upper()
        if cs not in _CHARSETS_DIRECT and cs not in _CHARSETS_SWAPPED:
            raise ValueError(
                "charset must be one of A,D,I (direct) or F,R,S (swapped); "
                "got '{}'".format(charset)
            )
        self._charset = cs
        self._swapped = cs in _CHARSETS_SWAPPED
        self._blank   = _BLANK_SWAPPED if self._swapped else _BLANK_DIRECT

        # Display-state mirrors
        self._blink    = _BLINK_OFF
        self._cursor   = _CURSOR_OFF
        self._active   = _DISP_ON
        self._h_orient = _H_NORMAL
        self._v_orient = _V_NORMAL
        self._scroll   = _ENTRY_NO_SHIFT
        self._dir      = _ENTRY_INC

    # ------------------------------------------------------------------
    # Public API  (LiquidCrystal_I2C / LCD API 1.0 compatible names)
    # ------------------------------------------------------------------

    def begin(self, cols=None, rows=None):
        """Initialise the display hardware.  Optionally override cols/rows."""
        if cols is not None:
            self._cols = cols
        if rows is not None:
            self._rows = rows
        self._init_display()

    def clear(self):
        """
        Clear all characters from the display and return cursor to home.

        For swapped-charset variants (F, R, S): performs a manual DDRAM fill
        with 0xA0 (the space glyph in these ROMs) because the hardware
        Clear_display command fills with 0x20, which is not a space.

        For direct-charset variants (A, D, I): uses the hardware command.
        """
        if self._swapped:
            self._clear_swapped()
        else:
            self._command(_CMD_CLEAR_DISPLAY)

    def home(self):
        """Return cursor to position (0, 0) without altering DDRAM."""
        self._command(_CMD_RETURN_HOME)

    def display(self):
        """Turn the display on (characters become visible)."""
        self._active = _DISP_ON
        self._set_display_control()

    def no_display(self):
        """Turn the display off (DDRAM content is preserved)."""
        self._active = _DISP_OFF
        self._set_display_control()

    def cursor(self):
        """Show the underline cursor at the current position."""
        self._cursor = _CURSOR_ON
        self._set_display_control()

    def no_cursor(self):
        """Hide the underline cursor."""
        self._cursor = _CURSOR_OFF
        self._set_display_control()

    def blink(self):
        """Enable the blinking-block cursor."""
        self._blink = _BLINK_ON
        self._set_display_control()

    def no_blink(self):
        """Disable the blinking-block cursor."""
        self._blink = _BLINK_OFF
        self._set_display_control()

    def set_cursor(self, col, row):
        """
        Move the cursor to (col, row), both 0-indexed.

        PCF2119x DDRAM layout (2x16 example):
          Display row 0  ->  DDRAM 0x00-0x0F
          Display row 1  ->  DDRAM 0x10-0x1F
          Off-screen     ->  DDRAM 0x20-0x4F  (used by scroll/shift)
        """
        addr = 0x10 * row + col
        self._command(_CMD_SET_DDRAM | (addr & 0x7F))

    def print(self, text):
        """
        Write a string at the current cursor position.
        Each character is translated through _ascii_to_lcd() for charset mapping.
        """
        for ch in text:
            self._write_char(ord(ch))

    def write(self, value):
        """
        Write a single character (integer codepoint) with charset translation.
        Use data() to bypass translation and address the ROM directly.
        """
        self._write_char(value)

    def data(self, value):
        """
        Write a raw byte to DDRAM without any charset translation.

        Useful for:
        - Accessing a specific ROM glyph position directly (e.g. special
          symbols only reachable in the 0x00-0x1F region of swapped ROMs).
        - Writing user-defined characters by CGRAM slot number (0-15);
          note the swap does NOT apply to 0x00-0x1F so write(0) and data(0)
          both emit CGRAM slot 0 regardless of charset.
        """
        self._i2c.writeto(self._addr, bytes([_CTRL_DATA, value & 0xFF]))
        self._wait_busy()

    def autoscroll(self):
        """
        Enable autoscroll: the display shifts left on each write so the new
        character appears to stay at the cursor position.

        WARNING (swapped charsets F, R, S): the hardware fills vacated
        right-hand columns with 0x20, which is not a space on these ROMs.
        Visible glyph artefacts will appear at the right edge.
        """
        self._scroll = _ENTRY_SHIFT
        self._set_entry_mode()

    def no_autoscroll(self):
        """Disable autoscroll."""
        self._scroll = _ENTRY_NO_SHIFT
        self._set_entry_mode()

    def left_to_right(self):
        """Set text direction left-to-right (DDRAM address increments)."""
        self._dir = _ENTRY_INC
        self._set_entry_mode()

    def right_to_left(self):
        """Set text direction right-to-left (DDRAM address decrements)."""
        self._dir = _ENTRY_DEC
        self._set_entry_mode()

    def scroll_display_left(self):
        """
        Shift the visible window one position left (hardware command 0x18).

        WARNING (swapped charsets F, R, S): the hardware fills the newly
        revealed right column with 0x20, which is not a space on these ROMs.
        Use scroll_display_left_safe() to avoid this artefact.
        """
        self._command(_CMD_SHIFT | _SHIFT_DISPLAY)          # 0x18

    def scroll_display_right(self):
        """
        Shift the visible window one position right (hardware command 0x1C).

        WARNING (swapped charsets F, R, S): the hardware fills the newly
        revealed left column with 0x20, which is not a space on these ROMs.
        Use scroll_display_right_safe() to avoid this artefact.
        """
        self._command(_CMD_SHIFT | _SHIFT_DISPLAY | _SHIFT_RIGHT)  # 0x1C

    def scroll_display_left_safe(self):
        """
        Shift the visible window one position left.

        For swapped charsets (F, R, S): pre-writes 0xA0 (correct blank) into
        the off-screen column that will be revealed before issuing the shift,
        preventing the 0x20-fill artefact.

        For direct charsets: identical to scroll_display_left().
        """
        if self._swapped:
            self._safe_scroll('left')
        else:
            self.scroll_display_left()

    def scroll_display_right_safe(self):
        """
        Shift the visible window one position right.

        For swapped charsets (F, R, S): pre-writes 0xA0 (correct blank) into
        the off-screen column that will be revealed before issuing the shift.

        For direct charsets: identical to scroll_display_right().
        """
        if self._swapped:
            self._safe_scroll('right')
        else:
            self.scroll_display_right()

    def cursor_left(self):
        """Move the cursor one position to the left (no display shift)."""
        self._command(_CMD_SHIFT)                           # 0x10

    def cursor_right(self):
        """Move the cursor one position to the right (no display shift)."""
        self._command(_CMD_SHIFT | _SHIFT_RIGHT)            # 0x14

    def create_char(self, char_num, rows_data):
        """
        Define a custom character glyph in CGRAM.

        Parameters
        ----------
        char_num  : CGRAM slot 0-15.  Slots 0-3 are also used by the icon
                    feature; avoid them if icons are active.
        rows_data : iterable of exactly 8 bytes; each is a 5-bit pixel row
                    (bits 4-0 used; bits 7-5 are ignored by the hardware).

        To display a custom character, call data(char_num) or write(char_num)
        where char_num is 0-15.  The swap translation does NOT apply to the
        range 0x00-0x1F so both methods emit the CGRAM slot directly.

        PCF2119x CGRAM addressing note:
        The Set_CGRAM command sets only bits 5-0 of the address.  Bit 6 can
        only be set via a Set_DDRAM command or by auto-increment past 0x3F.
        Slots 8-15 (cgram_addr 64-127) therefore need an extra DDRAM command
        to prime bit 6 before the CGRAM address is issued, using the
        _CTRL_CONTINUED interleave mechanism.
        """
        char_num  &= 0x0F
        cgram_addr = char_num * 8

        if char_num >= 8:
            self._i2c.writeto(self._addr, bytes([
                _CTRL_CONTINUED,
                _CMD_SET_DDRAM | (cgram_addr & 0x7F),   # sets bit 6
                _CTRL_CMD,
                _CMD_SET_CGRAM | (cgram_addr & 0x3F),   # sets bits 5-0
            ]))
        else:
            self._i2c.writeto(self._addr, bytes([
                _CTRL_CMD,
                _CMD_SET_CGRAM | (cgram_addr & 0x3F),
            ]))
        self._wait_busy()

        self._i2c.writeto(self._addr, bytes([_CTRL_DATA] + list(rows_data)[:8]))
        self._wait_busy()

    # ------------------------------------------------------------------
    # PCF2119x hardware-specific extensions
    # ------------------------------------------------------------------

    def normal_horizontal_orientation(self):
        """Normal (left-to-right) column scan order."""
        self._h_orient = _H_NORMAL
        self._set_display_config()

    def reverse_horizontal_orientation(self):
        """Reversed column scan order (mirror horizontally)."""
        self._h_orient = _H_REVERSE
        self._set_display_config()

    def normal_vertical_orientation(self):
        """Normal (top-to-bottom) row scan order."""
        self._v_orient = _V_NORMAL
        self._set_display_config()

    def reverse_vertical_orientation(self):
        """Reversed row scan order (flip vertically)."""
        self._v_orient = _V_REVERSE
        self._set_display_config()

    def get_address_point(self):
        """
        Read the current address-counter value from the controller.
        Returns the 7-bit DDRAM or CGRAM address (bit 7 is the busy flag,
        masked out before returning).
        """
        self._i2c.writeto(self._addr, bytes([_CTRL_CMD]))
        return self._i2c.readfrom(self._addr, 1)[0] & 0x7F

    def set_address_point(self, new_addr):
        """Directly set the DDRAM address pointer (0x00-0x4F)."""
        self._command(_CMD_SET_DDRAM | (new_addr & 0x7F))

    # ------------------------------------------------------------------
    # Private: low-level I2C helpers
    # ------------------------------------------------------------------

    def _command(self, value):
        """Send a single command byte to the Instruction Register."""
        self._i2c.writeto(self._addr, bytes([_CTRL_CMD, value & 0xFF]))
        self._wait_busy()

    def _write_char(self, value):
        """Send one character to DDRAM applying charset translation."""
        self._i2c.writeto(self._addr, bytes([_CTRL_DATA, self._ascii_to_lcd(value)]))
        self._wait_busy()

    def _wait_busy(self, max_retry=_MAX_RETRY):
        """
        Poll the busy flag (IR bit 7) until the controller reports ready.
        The PCF2119x is typically busy for under 100 us after most commands.
        A 50 us sleep between polls keeps bus traffic low.
        """
        self._i2c.writeto(self._addr, bytes([_CTRL_CMD]))
        for _ in range(max_retry):
            if not (self._i2c.readfrom(self._addr, 1)[0] & _BUSY_FLAG):
                return
            time.sleep_us(50)
        # Timeout: controller may be unresponsive; continue anyway

    # ------------------------------------------------------------------
    # Private: state-composing helpers
    # ------------------------------------------------------------------

    def _set_display_control(self):
        """Recompose and send the Display_ctl byte from current state."""
        self._command(_CMD_DISPLAY_CTRL | self._active | self._cursor | self._blink)

    def _set_entry_mode(self):
        """Recompose and send the Entry_mode byte from current state."""
        self._command(_CMD_ENTRY_MODE | self._scroll | self._dir)

    def _set_display_config(self):
        """
        Update Disp_conf (flip flags) via the extended instruction set.
        Switch to extended IS, write Disp_conf, return to basic IS – all in
        a single I2C transaction.
        """
        self._i2c.writeto(self._addr, bytes([
            _CTRL_CMD,
            _CMD_FUNCTION_EXT,
            _DISP_CONF_BASE | self._h_orient | self._v_orient,
            _CMD_FUNCTION_BASIC,
        ]))
        self._wait_busy()

    # ------------------------------------------------------------------
    # Private: initialisation
    # ------------------------------------------------------------------

    def _init_display(self):
        """
        Full hardware initialisation sequence (single I2C transaction):
          1.  Function_set (basic IS)
          2.  Entry_mode
          3.  Curs_disp_shift (cursor right)
          4.  Function_set (extended IS)
          5.  Disp_conf
          6.  Temp_ctl       (TC1=0, TC2=0 - display panel dependent)
          7.  HV_gen         (3-stage charge pump - panel dependent)
          8.  VLCDset        (VA=31 ~ 4.30 V - panel dependent)
          9.  Function_set   (back to basic IS)
         10.  Set_DDRAM      (address = 0)
         11.  Return_home

        The Temp_ctl, HV_gen, and VLCDset values match the original library
        and work with BT21605 / common PCF2119RU panels.  Adjust the three
        marked bytes if your panel requires different contrast or voltage.
        """
        self._i2c.writeto(self._addr, bytes([
            _CTRL_CMD,
            _CMD_FUNCTION_BASIC,
            _CMD_ENTRY_MODE | self._dir | self._scroll,
            _CMD_SHIFT | _SHIFT_RIGHT,                         # cursor moves right
            _CMD_FUNCTION_EXT,
            _DISP_CONF_BASE | self._h_orient | self._v_orient,
            0x10,                                              # Temp_ctl  (panel dependent)
            0x42,                                              # HV_gen    (panel dependent)
            0x9F,                                              # VLCDset   (panel dependent)
            _CMD_FUNCTION_BASIC,
            _CMD_SET_DDRAM,                                    # DDRAM address = 0x00
            _CMD_RETURN_HOME,
        ]))
        self._wait_busy()
        self.clear()
        self._set_display_control()

    # ------------------------------------------------------------------
    # Private: clear for swapped charsets
    # ------------------------------------------------------------------

    def _clear_swapped(self):
        """
        Manual DDRAM clear required for swapped-charset variants (F, R, S).

        Procedure from the PCF2119x datasheet:
          1. Switch display off
          2. Write blank pattern (0xA0) to all 80 DDRAM addresses
          3. Switch display back on

        0xA0 is used because:  space_glyph_in_ROM = 0x20 + 0x80 = 0xA0

        The I2C buffer limit of ~32 bytes per transaction means the 80-byte
        DDRAM must be written in three chunks:
          Chunk 0: addr 0x00, 27 bytes -> DDRAM 0x00-0x1A
          Chunk 1: addr 0x1B, 27 bytes -> DDRAM 0x1B-0x35
          Chunk 2: addr 0x36, 26 bytes -> DDRAM 0x36-0x4F
        """
        was_on = (self._active == _DISP_ON)
        self.no_display()

        for start_addr, count in ((0x00, 27), (0x1B, 27), (0x36, 26)):
            buf = bytes([
                _CTRL_CONTINUED,
                _CMD_SET_DDRAM | (start_addr & 0x7F),
                _CTRL_DATA,
            ]) + bytes([_BLANK_SWAPPED] * count)
            self._i2c.writeto(self._addr, buf)
            self._wait_busy()

        self.home()
        if was_on:
            self.display()

    # ------------------------------------------------------------------
    # Private: safe scroll for swapped charsets
    # ------------------------------------------------------------------

    def _safe_scroll(self, direction):
        """
        Software-assisted scroll for swapped-charset variants.

        Pre-writes 0xA0 into the off-screen DDRAM column that will be
        revealed by the hardware shift, preventing the 0x20-fill artefact.

        For a left scroll the column immediately to the right of the visible
        area (col = _cols) on each row is blanked before shifting.
        For a right scroll the column immediately to the left of the visible
        area wraps around; address (0x10*row - 1) & 0x7F targets that cell.
        """
        if direction == 'left':
            for row in range(self._rows):
                addr = (0x10 * row + self._cols) & 0x7F
                self._command(_CMD_SET_DDRAM | addr)
                self._i2c.writeto(self._addr, bytes([_CTRL_DATA, _BLANK_SWAPPED]))
                self._wait_busy()
            self._command(_CMD_SHIFT | _SHIFT_DISPLAY)              # 0x18
        else:
            for row in range(self._rows):
                addr = (0x10 * row - 1) & 0x7F
                self._command(_CMD_SET_DDRAM | addr)
                self._i2c.writeto(self._addr, bytes([_CTRL_DATA, _BLANK_SWAPPED]))
                self._wait_busy()
            self._command(_CMD_SHIFT | _SHIFT_DISPLAY | _SHIFT_RIGHT)  # 0x1C

    # ------------------------------------------------------------------
    # Private: character translation
    # ------------------------------------------------------------------

    def _ascii_to_lcd(self, ch):
        """
        Translate a Unicode/ASCII codepoint to the PCF2119x ROM address.

        Swapped variants (F, R, S):
          0x00-0x1F  ->  unchanged      CGRAM slots / control range
          0x20-0x7F  ->  ch + 0x80      printable ASCII -> ROM at 0xA0-0xFF
          0x80-0x9F  ->  unchanged      upper CGRAM slots 16-31
          0xA0-0xFF  ->  ch - 0x80      explicit access to lower ROM half

        Direct variants (A, D, I):
          All values passed through unchanged.
        """
        ch &= 0xFF
        if self._swapped:
            if 0x20 <= ch <= 0x7F:
                return ch + 0x80
            if 0xA0 <= ch <= 0xFF:
                return ch - 0x80
        return ch


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_lcd(sda_pin=8, scl_pin=9, freq=100_000,
             i2c_addr=0x3A, cols=16, rows=2, charset='R'):
    """
    Construct a SoftI2C bus and return a fully initialised LCD_PCF2119x.

    charset defaults to 'R' - the variant most commonly encountered on
    surplus/hobbyist markets (PCF2119RU).

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
