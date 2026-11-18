# Extraction and ELF fixups

The tree uses `ExtractUtilsModule('tulip', 'xiaomi', check_elf=True)` and generates
one vendor tree, `vendor/xiaomi/tulip`. The FM and IR lists retain their product
guards. No common device or vendor tree is needed. Python resolves extract-utils
relative to the script, so invoking it from another working directory works too.

In an Android checkout with Python extract-utils and extract-tools installed:

```sh
./extract-files.py /path/to/dump
./setup-makefiles.py
```

`--kang` records input and output hashes when deliberately changing a blob source.
Normal extraction preserves pinned sources. Entries with fixups use
`path;OPTIONS|source_sha1|patched_sha1` when both hashes are known. Hash generation
and list updates are handled by LineageOS `tools/extract-utils`; a separate
`update-sha1sums.py` is not required. To intentionally refresh hashes from a
chosen source, run:

```sh
./extract-files.py --kang /path/to/dump
```

## Reference changes

The Python migration and vendor namespace imports follow pix106's
[ec333555](https://github.com/pix106/android_device_xiaomi_sdm660-common/commit/ec333555b5cd09a07bcfad2a7bab2aa1634c5989).
Library fixup keys use module names without `.so`, matching extract-utils' API,
and accompany `MODULE_SUFFIX=_vendor` in the lists.

ELF enforcement follows
[89f790fb](https://github.com/pix106/android_device_xiaomi_sdm660-common/commit/89f790fb32093ee939792a09f1d95dd1ba90044d)
and [fdf128d4](https://github.com/pix106/android_device_xiaomi_sdm660-common/commit/fdf128d42a7580f9ab495fa0b410a6f67677a30e).
`BUILD_BROKEN_ELF_PREBUILT_PRODUCT_COPY_FILES` is removed, and the old direct
copies of VNDK libraries use `libhidlbase-v32` and `libutils-v33` modules from
`hardware/lineage/compat`. This requires those compatibility modules in the
platform checkout. Generated modules keep ELF checking and dependency generation
enabled.

Consumer IR renames use `FIX_SONAME`, following
[ac00e73e](https://github.com/pix106/android_device_xiaomi_sdm660-common/commit/ac00e73e1da7f3f340d009a908f592e2ac6322b0).
Inspection of tulip's Goodix blob confirmed its incorrect SONAME, so that entry
also uses `FIX_SONAME`. The logging fix adds `liblog.so` to libdirac; the
reference's `liglog.so` spelling is not used.

Lavender's [Python port](https://github.com/pix106/android_device_xiaomi_lavender/commit/af54c7902d6bd52b4073ce8e0c78e8852991d2de)
provides the faceproc symbol-version and fingerprint HIDL migration patterns.
Tulip's faceproc has the same three `LIBC_PRIVATE` imports. Its fingerprint
libraries move to `libhidlbase-v32` and drop obsolete transport/binder wrapper
dependencies. The existing Mlipay, Widevine, camera, and watermark shim behavior
is retained. Tulip's imglib also has duplicate `libfastcvopt.so` dependencies;
the fix removes the duplicate by name while retaining its ELF layout.

Lavender-specific chromatix names, blanket `DISABLE_DEPS` entries, and the Megvii
shim are not imported. Tulip's inspected lowlight blob does not need the
reference's `libstdc++` rewrite, and its imglib does not link the Megvii library.
Legacy paths without a partition prefix now explicitly name `system`.

## Camera patch

`blob_fixups/camera.py` ports the supplied `patch_camera_displayservice.sh` logic:

1. Switch the displayservice dependency and mangled namespace from Android to
   Lineage, as in [payton adc91ab](https://github.com/moto-sdm660/android_device_motorola_payton/commit/adc91ab).
2. Alias the specified unresolved HIDL methods to `IEventCallback::ping`.
3. Update the two Gralloc handle loads from `0x34/0x38` to `0x48/0x4c`, as in
   [msm8998 a26d58c](https://github.com/xiaomi-msm8998-devs/android_device_xiaomi_msm8998-common/commit/a26d58c).

The extractor invokes this helper directly. It never runs patchelf on the camera
HAL. The pinned input already links `libcamera_sdm660_shim.so`; the callback
rejects an unexpected input missing that dependency. All changes are planned and
validated before writing. The helper checks ARM32 ELF structure, string sharing,
defined symbols, unique executable Gralloc patterns, and unchanged file size,
ELF headers, program headers, and section headers. Already patched and partially
patched inputs are supported.

The standalone interface retains inspection and optional library-export checks:

```sh
python3 blob_fixups/camera.py --check camera.sdm660.so
python3 blob_fixups/camera.py camera.sdm660.so lineage.frameworks.displayservice@1.0.so
```

`--check` returns 3 when patches are pending, 0 when complete, and 1 on invalid
input. `--all-ibase` also redirects `notifySyspropsChanged` and
`setHALInstrumentation`; normal extraction leaves these two methods alone,
matching the supplied script's default. With a reference ARM32 Lineage library,
its exported symbols determine which safe methods need aliases, and every
displayservice import is checked against that library. A missing functional
method is an error.

Standalone patching creates an unused `.bak`, `.bak.1`, etc. before replacing the
file atomically. Extraction relies on extract-utils' backup/hash handling and
does not put backup files in the generated vendor tree.

Verified pinned camera transformation:

| State | SHA-1 |
| --- | --- |
| Input | `78b9c0db7f8372dec2e5b3713d7ad45e6f35e109` |
| Default patched output | `450a705c507c07a8d18cf93caec7f7cf8dece18e` |

The published vendor camera `da853ffadee6d7bce9557a347f43ad351c0f7c2e` already has
additional IBase aliases. The helper accepts that state without changing it;
it is not substituted for the canonical pinned input/output pair.

## Graphics downgrade revert

The build configuration had already reverted
[0f16af12](https://github.com/sundrams-playground/device_xiaomi_bouquet-common/commit/0f16af1288a73ae5d6799a0e60f26a32766bb86f),
but the HDR, SDM, Vulkan, and postprocessing lists still selected downgraded
`LA.UM.8.2.1.r1-05600-sdm660` files. Those sections now match the commit's parent
S62Pro versions, including `vulkan.adreno.so`, the missing 32-bit SDM vendor API
library, and display color 1.2. This agrees with the existing newer display
packages and `ro.hardware.vulkan=adreno`.

The main GPU section also uses the original S62Pro selection, including its
OpenCL, Vulkan tools, GPU data producer, and RenderScript libraries. Tulip's
32-bit camera HDR override is retained. This completes the graphics revert
without selecting the reference tree's newer Zebra/QSSI blob sets.

## Validation and remaining build work

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The tests cover camera patching, partial/repeated patches, export validation,
invalid ELF rejection without writes, shared strings, backup behavior, header
preservation, and duplicate dependency strings at different offsets.

The fixups were also exercised on real tulip/bouquet vendor files using
Lineage extract-utils `9d3f68f` and patchelf 0.18. All 17 applicable file fixups
were idempotent. Python makefile generation completed with 910 uniquely named
modules, no ELF-check disables, and one vendor tree.

The current public vendor repositories have 40 pre-existing source hash
differences relative to the tree's pinned audio/media/pm-service selections.
Those pins are preserved; build-file generation using the available files does
not establish that the correct pinned source set has been extracted. Matching
source dumps or vendor files are still required for those entries. Actual Soong
ELF/symbol checks and device camera/fingerprint testing require the complete
Android build and hardware; makefile generation alone does not validate them.
