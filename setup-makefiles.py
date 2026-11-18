#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    script = Path(__file__).resolve().with_name('extract-files.py')
    sys.argv = [str(script), '--regenerate_makefiles', *sys.argv[1:]]
    runpy.run_path(str(script), run_name='__main__')
