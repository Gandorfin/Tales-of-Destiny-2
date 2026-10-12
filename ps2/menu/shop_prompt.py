"""Give the shop's sell confirmation its text back (the "iH*" prompt).

The 2008 menu patch appended an English string table to 06803.md1 and
pointed the module's string pointers at it. For the sell confirmation it
wrote the new address (0x2A4869, the appended "Sell?" prompt) to the wrong
place: over the first four bytes of the Japanese prompt at 0x8A18 instead
of into the pointer at 0x87A8. That pointer still leads to 0x8A18, where
the bytes 69 48 2A 00 of the stray address read as the text "iH*" followed
by a terminator, and that is what the game shows when an item is sold.

The fix is the write the old patch meant to make: the pointer at 0x87A8
gets the address that sits at 0x8A18. Nothing else changes, so the buy
confirmation ("Buy?") and the sell confirmation ("Sell?") come from the
same appended table.
"""
import struct

BASE = 0x29BB00                 # load address of the module
POINTER = 0x87A8                # the sell confirmation's string pointer
STRAY = 0x8A18                  # where the 2008 patch put the address
PROMPT = 0x8D69                 # the appended English prompt
TEXT = b'Sell?\x01 \x01\x095\x00\x00\x00Sell  \x096\x00\x00\x00Cancel\x00'


def apply(data):
    """Return (changed, current); raise ValueError on an unknown layout."""
    if len(data) < PROMPT + len(TEXT) or bytes(data[PROMPT:PROMPT + len(TEXT)]) != TEXT:
        raise ValueError('shop sell prompt: the appended English prompt is missing')
    wanted = struct.pack('<L', BASE + PROMPT)
    if bytes(data[STRAY:STRAY + 4]) != wanted:
        raise ValueError('shop sell prompt: unexpected bytes at 0x%X' % STRAY)
    pointer = bytes(data[POINTER:POINTER + 4])
    if pointer == wanted:
        return 0, 1
    if pointer != struct.pack('<L', BASE + STRAY):
        raise ValueError('shop sell prompt: unexpected pointer at 0x%X' % POINTER)
    data[POINTER:POINTER + 4] = wanted
    return 1, 0
