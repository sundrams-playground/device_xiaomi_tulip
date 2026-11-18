# SPDX-License-Identifier: Apache-2.0
"""Regression tests use synthetic ARM ELFs; proprietary binaries are not required."""

from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blob_fixups.camera import (
    CameraPatchError, Elf32, GRALLOC, LIN_PREFIX, NEW_DEP, NEW_NS, OLD_DEP,
    OLD_NS, PING, blob_fixup_camera, patch_camera, patch_camera_bytes,
)
from blob_fixups.elf import remove_duplicate_needed

ROOT = Path(__file__).resolve().parents[1]


def symbol(cls, method):
    return LIN_PREFIX + str(len(cls)).encode() + cls + str(len(method)).encode() + method + b'Ev'


def elf_fixture(symbols=None, library=False, needed=None):
    """ELF32 with a dynamic table, SysV symbol count, and executable Gralloc code."""
    if symbols is None:
        symbols = [(symbol(b'IEventCallback', b'linkToDeath').replace(NEW_NS, OLD_NS), False),
                   (symbol(b'IDisplayService', b'getService').replace(NEW_NS, OLD_NS), False)]
    if needed is None:
        needed = [] if library else [OLD_DEP, b'libcamera_sdm660_shim.so']
    data = bytearray(0x4000)
    ident = b'\x7fELF\x01\x01\x01' + b'\0' * 9
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, ident, 3, 40, 1, 0, 52, 0, 0,
                     52, 32, 2, 40, 0, 0)
    struct.pack_into('<8I', data, 52, 1, 0, 0x1000, 0x1000, len(data), len(data), 5, 0x1000)
    strings = bytearray(b'\0')

    def add_string(value):
        off = len(strings)
        strings.extend(value + b'\0')
        return off

    entries = [(1, add_string(name)) for name in needed]
    if library:
        entries.append((14, add_string(NEW_DEP)))
    for i, (name, defined) in enumerate(symbols, 1):
        name_off = add_string(name)
        struct.pack_into('<IIIBBH', data, 0x1000 + i * 16, name_off, 0, 0, 0x12, 0, int(defined))
    data[0x300:0x300 + len(strings)] = strings
    struct.pack_into('<2I', data, 0x1A00, 1, len(symbols) + 1)
    entries += [(5, 0x1300), (10, len(strings)), (6, 0x2000), (11, 16), (4, 0x2A00), (0, 0)]
    for i, entry in enumerate(entries):
        struct.pack_into('<iI', data, 0x1800 + i * 8, *entry)
    struct.pack_into('<8I', data, 84, 2, 0x1800, 0x2800, 0x2800,
                     len(entries) * 8, len(entries) * 8, 6, 4)
    for i, (_, pattern, _) in enumerate(GRALLOC):
        data[0x2000 + i * 64:0x2000 + i * 64 + len(pattern)] = pattern
    return bytes(data)


class CameraFixupTests(unittest.TestCase):
    def test_patch_and_idempotency_preserve_headers(self):
        original = elf_fixture()
        patched, report = patch_camera_bytes(original)
        self.assertTrue(report)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(patched[:116], original[:116])
        self.assertEqual(Elf32(patched).segments, Elf32(original).segments)
        self.assertIn(NEW_DEP, [n for _, n in Elf32(patched).needed()])
        self.assertNotIn(OLD_NS, patched)
        self.assertIn(PING, patched)
        self.assertIn(symbol(b'IDisplayService', b'getService'), patched)
        for _, old, new in GRALLOC:
            self.assertNotIn(old, patched)
            self.assertEqual(patched.count(new), 1)
        self.assertEqual(patch_camera_bytes(patched), (patched, []))

    def test_partial_patch_completes(self):
        original = elf_fixture().replace(OLD_DEP, NEW_DEP)
        original = original.replace(GRALLOC[0][1], GRALLOC[0][2])
        expected, _ = patch_camera_bytes(elf_fixture())
        self.assertEqual(patch_camera_bytes(original)[0], expected)

    def test_all_ibase_is_opt_in(self):
        extra = symbol(b'IEventCallback', b'notifySyspropsChanged')
        original = elf_fixture([(extra.replace(NEW_NS, OLD_NS), False)])
        self.assertIn(extra, patch_camera_bytes(original)[0])
        self.assertNotIn(extra, patch_camera_bytes(original, all_ibase=True)[0])

    def test_library_exports_drive_aliases(self):
        extra = symbol(b'IEventCallback', b'setHALInstrumentation')
        get_service = symbol(b'IDisplayService', b'getService')
        original = elf_fixture([(extra, False), (get_service, False)])
        library = elf_fixture([(PING, True), (get_service, True)], library=True)
        patched, _ = patch_camera_bytes(original, library)
        self.assertNotIn(extra, patched)
        self.assertIn(get_service, patched)

    def test_missing_functional_export_rejected(self):
        original = elf_fixture([(symbol(b'IDisplayService', b'getService'), False)])
        library = elf_fixture([(PING, True)], library=True)
        with self.assertRaisesRegex(CameraPatchError, 'functional'):
            patch_camera_bytes(original, library)

    def test_missing_ping_or_wrong_soname_rejected(self):
        library = elf_fixture([(symbol(b'IDisplayService', b'getService'), True)], library=True)
        with self.assertRaisesRegex(CameraPatchError, 'ping'):
            patch_camera_bytes(elf_fixture(), library)
        library = elf_fixture([(PING, True)], library=True).replace(NEW_DEP, OLD_DEP)
        with self.assertRaisesRegex(CameraPatchError, 'SONAME'):
            patch_camera_bytes(elf_fixture(), library)

    def test_defined_symbol_rename_rejected(self):
        with self.assertRaisesRegex(CameraPatchError, 'defined symbol'):
            patch_camera_bytes(elf_fixture([(PING.replace(NEW_NS, OLD_NS), True)]))

    def test_duplicate_or_missing_gralloc_pattern_rejected(self):
        original = elf_fixture()
        with self.assertRaisesRegex(CameraPatchError, 'Gralloc'):
            patch_camera_bytes(original.replace(GRALLOC[0][1], b'\0' * len(GRALLOC[0][1])))
        duplicate = original + GRALLOC[0][1]
        with self.assertRaisesRegex(CameraPatchError, 'Gralloc'):
            patch_camera_bytes(duplicate)

    def test_non_executable_gralloc_rejected(self):
        original = bytearray(elf_fixture())
        struct.pack_into('<I', original, 52 + 24, 4)
        with self.assertRaisesRegex(CameraPatchError, 'executable'):
            patch_camera_bytes(bytes(original))

    def test_suffix_shared_dependency_rejected(self):
        original = bytearray(elf_fixture())
        # A DT_SONAME reference into the middle of the displayservice DT_NEEDED.
        struct.pack_into('<iI', original, 0x1800 + 7 * 8, 14, 5)
        # Grow PT_DYNAMIC to include a new terminator, using existing file padding.
        struct.pack_into('<II', original, 84 + 16, 9 * 8, 9 * 8)
        with self.assertRaisesRegex(CameraPatchError, 'suffix-shared'):
            patch_camera_bytes(bytes(original))

    def test_invalid_elf_never_writes_or_backs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'camera.so'
            for original in [b'not ELF', elf_fixture()[:100], elf_fixture().replace(b'\x7fELF\x01', b'\x7fELF\x02', 1)]:
                p.write_bytes(original)
                with self.assertRaises(CameraPatchError):
                    patch_camera(p)
                self.assertEqual(p.read_bytes(), original)
                self.assertEqual(list(Path(directory).iterdir()), [p])

    def test_check_and_backup_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'camera.so'
            original = elf_fixture()
            p.write_bytes(original)
            self.assertTrue(patch_camera(p, check=True)[0])
            self.assertEqual(p.read_bytes(), original)
            backup = Path(str(p) + '.bak')
            backup.write_bytes(b'previous backup')
            self.assertTrue(patch_camera(p)[0])
            self.assertEqual(backup.read_bytes(), b'previous backup')
            self.assertEqual(Path(str(p) + '.bak.1').read_bytes(), original)
            self.assertFalse(patch_camera(p)[0])
            self.assertFalse(Path(str(p) + '.bak.2').exists())

    def test_cli_check_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'camera.so'
            p.write_bytes(elf_fixture())
            result = subprocess.run([sys.executable, str(ROOT / 'blob_fixups/camera.py'), '--check', str(p)], capture_output=True)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(p.read_bytes(), elf_fixture())

    def test_extraction_keeps_backups_out_of_vendor(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'camera.so'
            p.write_bytes(elf_fixture())
            blob_fixup_camera(None, None, str(p))
            self.assertEqual(list(Path(directory).iterdir()), [p])
            p.write_bytes(elf_fixture(needed=[OLD_DEP]))
            with self.assertRaisesRegex(CameraPatchError, 'shim'):
                blob_fixup_camera(None, None, str(p))

    def test_duplicate_needed_strings_at_different_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'imglib.so'
            original = elf_fixture(needed=[b'libfastcvopt.so', b'libfastcvopt.so', b'liblog.so'])
            p.write_bytes(original)
            remove_duplicate_needed(None, None, str(p))
            fixed = p.read_bytes()
            self.assertEqual([name for _, name in Elf32(fixed).needed()], [b'libfastcvopt.so', b'liblog.so'])
            self.assertEqual(fixed[:116], original[:116])
            self.assertEqual(len(fixed), len(original))
            remove_duplicate_needed(None, None, str(p))
            self.assertEqual(p.read_bytes(), fixed)


if __name__ == '__main__':
    unittest.main()
