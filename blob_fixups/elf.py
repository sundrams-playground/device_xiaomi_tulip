# SPDX-License-Identifier: Apache-2.0
"""Small ELF fixups that keep the file's existing layout."""

from pathlib import Path
import struct


def remove_duplicate_needed(ctx, file, file_path, *args, **kwargs):
    path = Path(file_path)
    data = bytearray(path.read_bytes())
    if data[:6] not in (b'\x7fELF\x01\x01', b'\x7fELF\x02\x01'):
        raise ValueError('Expected a little-endian ELF')
    is64 = data[4] == 2
    phoff = struct.unpack_from('<Q' if is64 else '<I', data, 32 if is64 else 28)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54 if is64 else 42)
    fmt = '<qQ' if is64 else '<iI'
    entsize = struct.calcsize(fmt)
    segments = []
    dynamic = None
    for i in range(phnum):
        off = phoff + i * phsize
        if is64:
            kind, _, offset, address, _, size, _, _ = struct.unpack_from('<II6Q', data, off)
        else:
            kind, offset, address, _, size, _, _, _ = struct.unpack_from('<8I', data, off)
        if kind == 1:
            segments.append((offset, address, size))
        elif kind == 2:
            dynamic = (offset, size)
    if dynamic is not None:
        dynoff, size = dynamic
        if dynoff + size > len(data) or size % entsize:
            raise ValueError('Invalid dynamic table')
        entries = []
        for pos in range(dynoff, dynoff + size, entsize):
            tag, value = struct.unpack_from(fmt, data, pos)
            if tag == 0:
                break
            entries.append((tag, value))
        else:
            raise ValueError('Unterminated dynamic table')
        tags = dict(entries)
        address, strsize = tags[5], tags[10]
        strtab = next((offset + address - vaddr for offset, vaddr, length in segments
                       if vaddr <= address and address + strsize <= vaddr + length), None)
        if strtab is None or strtab + strsize > len(data):
            raise ValueError('Invalid dynamic string table')
        seen = set()
        unique = []
        for tag, value in entries:
            if tag == 1:
                end = data.find(b'\0', strtab + value, strtab + strsize)
                if not 0 <= value < strsize or end < 0:
                    raise ValueError('Invalid DT_NEEDED string')
                name = bytes(data[strtab + value:end])
                if name in seen:
                    continue
                seen.add(name)
            unique.append((tag, value))
        changed = len(unique) != len(entries)
        if changed:
            entries = unique
            entries.extend([(0, 0)] * (size // entsize - len(entries)))
            for i, entry in enumerate(entries):
                struct.pack_into(fmt, data, dynoff + i * entsize, *entry)
            path.write_bytes(data)
        return
    raise ValueError('No dynamic table')
