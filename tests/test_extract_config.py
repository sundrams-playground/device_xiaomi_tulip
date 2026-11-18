# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('extract_utils'), 'Requires Android tools/extract-utils on PYTHONPATH')
class ExtractionConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from extract_utils.module import ProprietaryFileType
        cls.module = runpy.run_path(str(ROOT / 'extract-files.py'))['module']
        # Allow metadata checks in a standalone checkout as well as Android.
        for pf in cls.module.proprietary_files:
            pf.file_list_path = str(ROOT / Path(pf.file_list_path).name)
        cls.module.parse(False, None)
        cls.files = cls.module.get_files(ProprietaryFileType.BLOBS)

    def test_elf_checks_and_fixup_hashes(self):
        from extract_utils.file import FileArgs
        self.assertTrue(self.module.check_elf)
        for file in self.files:
            self.assertNotIn(FileArgs.DISABLE_CHECKELF, file.args, file.dst)
            self.assertNotIn(FileArgs.DISABLE_DEPS, file.args, file.dst)
            if file.fixup_hash is not None:
                self.assertTrue(self.module.should_fixup_file(file), file.dst)

    def test_suffix_mapping_matches_generated_module_names(self):
        from extract_utils.file import FileArgs
        for file in self.files:
            if file.args.get(FileArgs.MODULE_SUFFIX) == '_vendor':
                name = Path(file.dst).stem
                self.assertEqual(self.module.lib_fixups[name](name, file.partition), f'{name}_vendor')

    def test_blob_fixups_match_tulip_files(self):
        destinations = {file.dst for file in self.files}
        self.assertEqual(len(destinations), len(self.files))
        self.assertFalse(set(self.module.blob_fixups) - destinations)
        for file in self.files:
            for path in [file.src, file.dst]:
                self.assertIn(path.split('/')[0], {'system', 'system_ext', 'vendor', 'product', 'odm'}, path)
        self.assertEqual(self.module.device, 'tulip')
        self.assertEqual(self.module.vendor, 'xiaomi')


if __name__ == '__main__':
    unittest.main()
