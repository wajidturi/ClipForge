"""Time-sortable UUIDv7 ids (RFC 9562). Python 3.12 has no uuid7, so we build one."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand & ((1 << 62) - 1)  # rand_b (62 bits)
    return uuid.UUID(int=value)
