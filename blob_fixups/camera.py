#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Patch tulip's ARM32 camera HAL without relocating ELF data.

Based on the user-supplied patch_camera_displayservice.sh, payton adc91ab,
and msm8998-common a26d58c. Only library/symbol strings and the two Gralloc
instructions may change. The extraction callback never invokes patchelf.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile

PT_LOAD, PT_DYNAMIC = 1, 2
DT_NEEDED, DT_HASH, DT_STRTAB, DT_SYMTAB = 1, 4, 5, 6
DT_STRSZ, DT_SONAME, DT_RPATH, DT_RUNPATH, DT_GNU_HASH = 10, 14, 15, 29, 0x6FFFFEF5
OLD_DEP = b'android.frameworks.displayservice@1.0.so'
NEW_DEP = b'lineage.frameworks.displayservice@1.0.so'
OLD_NS = b'7android10frameworks14displayservice'
NEW_NS = b'7lineage10frameworks14displayservice'
LIN_PREFIX = b'_ZN7lineage10frameworks14displayservice4V1_0'
PING = LIN_PREFIX + b'14IEventCallback4pingEv'
COMMIT_UNRESOLVED = {
    b'linkToDeath', b'unlinkToDeath', b'getDebugInfo', b'getHashChain',
    b'interfaceChain', b'interfaceDescriptor', b'debug', b'registerForNotifications',
}
EXTRA_IBASE = {b'notifySyspropsChanged', b'setHALInstrumentation'}
IBASE_METHODS = COMMIT_UNRESOLVED | EXTRA_IBASE | {b'ping'}
GRALLOC = (
    ('size/offset log load', bytes.fromhex('c168d0e90d20cde90320'),
     bytes.fromhex('c168d0e91220cde90320')),
    ('size load', bytes.fromhex('dbf80010089a496bc6e90421'),
     bytes.fromhex('dbf80010089a896cc6e90421')),
)


class CameraPatchError(ValueError):
    pass


class Elf32:
    """Read ELF32 LE dynamic strings/symbols with file and segment bounds checks."""

    def __init__(self, data):
        self.data = data
        if len(data) < 52 or data[:6] != b'\x7fELF\x01\x01':
            raise CameraPatchError('Expected a 32-bit little-endian ELF')
        if self.unpack('<H', 18)[0] != 40:
            raise CameraPatchError('Expected an ARM ELF')
        self.phoff, self.shoff = self.unpack('<II', 28)
        self.phentsize, self.phnum, self.shentsize, self.shnum, _ = self.unpack('<5H', 42)
        if self.phentsize != 32 or not self.phnum:
            raise CameraPatchError('Invalid program header table')
        self.phend = self.phoff + self.phnum * self.phentsize
        self.bounds(self.phoff, self.phnum * self.phentsize)
        self.segments = [self.unpack('<8I', self.phoff + i * 32) for i in range(self.phnum)]
        for seg in self.segments:
            self.bounds(seg[1], seg[4])
        dynamic = [s for s in self.segments if s[0] == PT_DYNAMIC]
        if len(dynamic) != 1:
            raise CameraPatchError('Expected exactly one PT_DYNAMIC segment')
        self.dynamic = []
        for off in range(dynamic[0][1], dynamic[0][1] + dynamic[0][4], 8):
            tag, value = self.unpack('<iI', off)
            if tag == 0:
                break
            self.dynamic.append((tag, value))
        else:
            raise CameraPatchError('Unterminated dynamic table')
        tags = dict(reversed(self.dynamic))
        if not {DT_STRTAB, DT_SYMTAB, DT_STRSZ} <= tags.keys():
            raise CameraPatchError('Missing dynamic string/symbol table')
        self.strsz = tags[DT_STRSZ]
        self.strtab = self.v2o(tags[DT_STRTAB], self.strsz)
        self.symtab = self.v2o(tags[DT_SYMTAB])
        self.nsyms = self.count_symbols(tags)
        self.bounds(self.symtab, self.nsyms * 16)

    def bounds(self, off, size):
        if off < 0 or size < 0 or off + size > len(self.data):
            raise CameraPatchError('ELF data extends beyond the file')

    def unpack(self, fmt, off):
        self.bounds(off, struct.calcsize(fmt))
        return struct.unpack_from(fmt, self.data, off)

    def v2o(self, address, size=1):
        for seg in self.segments:
            if seg[0] == PT_LOAD and seg[2] <= address and address + size <= seg[2] + seg[4]:
                return seg[1] + address - seg[2]
        raise CameraPatchError(f'Address 0x{address:x} is not file-backed by PT_LOAD')

    def count_symbols(self, tags):
        if self.shnum:
            if self.shentsize != 40:
                raise CameraPatchError('Invalid section header size')
            self.bounds(self.shoff, self.shnum * self.shentsize)
            for i in range(self.shnum):
                sh = self.unpack('<10I', self.shoff + i * self.shentsize)
                if sh[1] == 11 and sh[4] == self.symtab:
                    if sh[9] != 16 or sh[5] % 16:
                        raise CameraPatchError('Invalid dynamic symbol entry size')
                    return sh[5] // 16
        if DT_HASH in tags:
            return self.unpack('<2I', self.v2o(tags[DT_HASH], 8))[1]
        if DT_GNU_HASH in tags:
            h = self.v2o(tags[DT_GNU_HASH], 16)
            buckets, first, bloom, _ = self.unpack('<4I', h)
            if not buckets:
                return first
            table = h + 16 + bloom * 4
            last = max(self.unpack(f'<{buckets}I', table))
            chain = table + buckets * 4
            if last < first:
                return first
            while not self.unpack('<I', chain + (last - first) * 4)[0] & 1:
                last += 1
            return last + 1
        raise CameraPatchError('Cannot determine dynamic symbol count')

    def cstr(self, offset):
        if not 0 <= offset < self.strsz:
            raise CameraPatchError('Invalid dynamic string offset')
        start = self.strtab + offset
        end = self.data.find(b'\0', start, self.strtab + self.strsz)
        if end == -1:
            raise CameraPatchError('Unterminated dynamic string')
        return self.data[start:end]

    def symbols(self):
        for i in range(self.nsyms):
            name, _, _, info, _, section = self.unpack('<IIIBBH', self.symtab + i * 16)
            yield name, info, section

    def needed(self):
        return [(v, self.cstr(v)) for tag, v in self.dynamic if tag == DT_NEEDED]

    def exports(self):
        return {self.cstr(n) for n, info, section in self.symbols()
                if section and info >> 4 in (1, 2) and self.cstr(n)}

    def string_refs(self):
        return {n for n, _, _ in self.symbols()} | {
            v for tag, v in self.dynamic if tag in (DT_NEEDED, DT_SONAME, DT_RPATH, DT_RUNPATH)
        }

    def no_inner_refs(self, start, end):
        if any(start < self.strtab + r < end for r in self.string_refs()):
            raise CameraPatchError('Refusing to overwrite a suffix-shared dynamic string')


def parse_symbol(name):
    if not name.startswith(LIN_PREFIX):
        return None
    rest = name[len(LIN_PREFIX):]
    match = re.match(rb'(\d+)', rest)
    if not match:
        return None
    length = int(match[1])
    cls = rest[match.end():match.end() + length]
    rest = rest[match.end() + length:]
    match = re.match(rb'(\d+)', rest)
    if not match:
        return None
    return cls, rest[match.end():match.end() + int(match[1])]


def patch_camera_bytes(original, lineage_library=None, all_ibase=False):
    """Plan and verify the complete patch before returning any modified bytes."""
    elf = Elf32(original)
    data = bytearray(original)
    allowed = []
    report = []
    exports = None
    if lineage_library is not None:
        library = Elf32(lineage_library)
        sonames = [library.cstr(v) for tag, v in library.dynamic if tag == DT_SONAME]
        if sonames != [NEW_DEP]:
            raise CameraPatchError('Reference library has the wrong SONAME')
        exports = library.exports()
        if PING not in exports:
            raise CameraPatchError('Reference library does not export IEventCallback::ping')

    def replace(start, old, new):
        if len(old) != len(new) or data[start:start + len(old)] != old:
            raise CameraPatchError('Unexpected bytes or replacement length')
        data[start:start + len(old)] = new
        allowed.append((start, start + len(old)))

    old_deps = [v for v, name in elf.needed() if name == OLD_DEP]
    new_deps = [v for v, name in elf.needed() if name == NEW_DEP]
    if old_deps:
        if len(set(old_deps)) != 1 or new_deps:
            raise CameraPatchError('Ambiguous displayservice dependency')
        start = elf.strtab + old_deps[0]
        elf.no_inner_refs(start, start + len(OLD_DEP))
        replace(start, OLD_DEP, NEW_DEP)
        report.append('DT_NEEDED: android -> lineage displayservice')
    elif not new_deps:
        raise CameraPatchError('Camera has no displayservice dependency')

    for name, _, section in elf.symbols():
        if section and OLD_NS in elf.cstr(name):
            raise CameraPatchError('Renaming a defined symbol would invalidate its hash table')
    namespace_hits = list(re.finditer(re.escape(OLD_NS), original))
    for match in namespace_hits:
        start = match.start()
        if elf.strtab <= start < elf.strtab + elf.strsz:
            string_start = original.rfind(b'\0', elf.strtab, start) + 1
            if string_start < elf.strtab:
                string_start = elf.strtab
            end = original.find(b'\0', start, elf.strtab + elf.strsz)
            if end == -1:
                raise CameraPatchError('Unterminated displayservice symbol')
            elf.no_inner_refs(string_start, end)
        replace(start, OLD_NS, NEW_NS)
    if namespace_hits:
        report.append(f'Symbol namespace: android -> lineage ({len(namespace_hits)} strings)')

    current = Elf32(bytes(data))
    done = set()
    for name_offset, _, section in current.symbols():
        if section:
            continue
        name = current.cstr(name_offset)
        parsed = parse_symbol(name)
        if not parsed or name == PING:
            continue
        cls, method = parsed
        if exports is not None:
            redirect = name not in exports
            safe = (cls == b'IEventCallback' and method in IBASE_METHODS) or method == b'registerForNotifications'
            if redirect and not safe:
                raise CameraPatchError(f'Cannot alias a functional displayservice method: {name!r}')
        else:
            redirect = method in COMMIT_UNRESOLVED or (all_ibase and method in EXTRA_IBASE)
        if not redirect:
            continue
        start = current.strtab + name_offset
        if start in done:
            continue
        if len(PING) > len(name):
            raise CameraPatchError('Ping name does not fit the original symbol')
        current.no_inner_refs(start, start + len(name))
        replace(start, name, PING.ljust(len(name), b'\0'))
        done.add(start)
        report.append(f'HIDL: {cls.decode()}::{method.decode()} -> IEventCallback::ping')

    for label, old, new in GRALLOC:
        old_count, new_count = data.count(old), data.count(new)
        if (old_count, new_count) not in ((1, 0), (0, 1)):
            raise CameraPatchError(f'Gralloc {label}: expected exactly one original or patched pattern, '
                                   f'found {old_count}/{new_count}')
        pattern = old if old_count else new
        start = data.find(pattern)
        if not any(s[0] == PT_LOAD and s[6] & 1 and s[1] <= start and
                   start + len(pattern) <= s[1] + s[4] for s in elf.segments):
            raise CameraPatchError(f'Gralloc {label}: pattern is outside executable PT_LOAD')
        if old_count:
            replace(start, old, new)
            report.append(f'Gralloc {label}: 0x34/0x38 -> 0x48/0x4c')

    result = bytes(data)
    patched = Elf32(result)
    if len(result) != len(original) or result[:52] != original[:52]:
        raise CameraPatchError('ELF size or header changed')
    if result[elf.phoff:elf.phend] != original[elf.phoff:elf.phend]:
        raise CameraPatchError('Program headers changed')
    shend = elf.shoff + elf.shnum * elf.shentsize
    if result[elf.shoff:shend] != original[elf.shoff:shend]:
        raise CameraPatchError('Section headers changed')
    mask = bytearray(len(original))
    for start, end in allowed:
        mask[start:end] = b'\1' * (end - start)
    if any(a != b and not mask[i] for i, (a, b) in enumerate(zip(original, result))):
        raise CameraPatchError('Unexpected change outside the planned byte ranges')
    needed = [name for _, name in patched.needed()]
    if NEW_DEP not in needed or OLD_DEP in needed or OLD_NS in result:
        raise CameraPatchError('Incomplete displayservice conversion')
    if exports is not None:
        missing = {patched.cstr(n) for n, _, section in patched.symbols()
                   if not section and patched.cstr(n).startswith(LIN_PREFIX)} - exports
        if missing:
            raise CameraPatchError(f'Unresolved displayservice import: {sorted(missing)[0]!r}')
    return result, report


def patch_camera(path, lineage_lib=None, all_ibase=False, check=False, backup=True):
    path = Path(path).resolve()
    original = path.read_bytes()
    library = Path(lineage_lib).read_bytes() if lineage_lib else None
    result, report = patch_camera_bytes(original, library, all_ibase)
    changed = result != original
    if check or not changed:
        return changed, report
    if backup:
        candidate = Path(str(path) + '.bak')
        index = 1
        while candidate.exists() or candidate.is_symlink():
            candidate = Path(f'{path}.bak.{index}')
            index += 1
        shutil.copy2(path, candidate)
    # Validate before writing; atomic replace never exposes a partial ELF.
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(result)
        shutil.copymode(path, temp)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return changed, report


def blob_fixup_camera(ctx, file, file_path, *args, **kwargs):
    # The pinned tulip camera already has the GraphicBuffer lock shim. Adding
    # it with patchelf here would undo the program-header preservation guarantee.
    elf = Elf32(Path(file_path).read_bytes())
    if b'libcamera_sdm660_shim.so' not in {n for _, n in elf.needed()}:
        raise CameraPatchError('Use the pinned tulip camera with libcamera_sdm660_shim.so already linked')
    patch_camera(file_path, backup=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='report only; exit 3 if patches are pending')
    parser.add_argument('--all-ibase', action='store_true', help='also alias notifySyspropsChanged/setHALInstrumentation')
    parser.add_argument('camera', type=Path)
    parser.add_argument('lineage_library', type=Path, nargs='?')
    args = parser.parse_args()
    try:
        changed, report = patch_camera(args.camera, args.lineage_library, args.all_ibase, args.check)
    except (CameraPatchError, OSError) as error:
        parser.exit(1, f'ERROR: {error}\n')
    print('\n'.join(report) if report else 'Already fully patched')
    if args.check:
        print('PATCHES PENDING' if changed else 'Fully patched')
        return 3 if changed else 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
