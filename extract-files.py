#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import sys

# Resolve extract-utils relative to this tree, including when called from elsewhere.
DEVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DEVICE_DIR.parents[2] / 'tools' / 'extract-utils'))
sys.path.insert(0, str(DEVICE_DIR))

from extract_utils.fixups_blob import blob_fixup
from extract_utils.fixups_lib import lib_fixups as default_lib_fixups
from extract_utils.main import ExtractUtils, ExtractUtilsModule

from blob_fixups.camera import blob_fixup_camera
from blob_fixups.elf import remove_duplicate_needed

namespace_imports = [
    'device/xiaomi/tulip',
    'hardware/qcom-caf/common/libqti-perfd-client',
    'hardware/qcom-caf/sdm660',
    'hardware/qcom-caf/wlan',
    'hardware/xiaomi',
    'vendor/qcom/opensource/commonsys/display',
    'vendor/qcom/opensource/commonsys-intf/display',
    'vendor/qcom/opensource/data-ipa-cfg-mgr-legacy-um',
    'vendor/qcom/opensource/dataservices',
    'vendor/qcom/opensource/display',
]


def lib_fixup_vendor_suffix(lib, partition):
    return f'{lib}_vendor' if partition == 'vendor' else None


# These are module names without .so, not proprietary file paths. Keep in sync
# with MODULE_SUFFIX=_vendor in the proprietary lists (pix106's Python port).
lib_fixups = {
    **default_lib_fixups,
    (
        'com.qualcomm.qti.dpm.api@1.0',
        'com.qualcomm.qti.imscmservice@2.0',
        'com.qualcomm.qti.imscmservice@2.1',
        'com.qualcomm.qti.imscmservice@2.2',
        'com.qualcomm.qti.uceservice@2.0',
        'com.qualcomm.qti.uceservice@2.1',
        'com.qualcomm.qti.uceservice@2.2',
        'com.qualcomm.qti.uceservice@2.3',
        'vendor.qti.data.factory@2.0',
        'vendor.qti.data.factory@2.1',
        'vendor.qti.data.factory@2.2',
        'vendor.qti.data.mwqem@1.0',
        'vendor.qti.data.slm@1.0',
        'vendor.qti.hardware.alarm@1.0',
        'vendor.qti.hardware.data.cne.internal.api@1.0',
        'vendor.qti.hardware.data.cne.internal.constants@1.0',
        'vendor.qti.hardware.data.cne.internal.server@1.0',
        'vendor.qti.hardware.data.connection@1.0',
        'vendor.qti.hardware.data.connection@1.1',
        'vendor.qti.hardware.data.dynamicdds@1.0',
        'vendor.qti.hardware.data.iwlan@1.0',
        'vendor.qti.hardware.data.latency@1.0',
        'vendor.qti.hardware.data.qmi@1.0',
        'vendor.qti.hardware.fm@1.0',
        'vendor.qti.hardware.mwqemadapter@1.0',
        'vendor.qti.hardware.radio.am@1.0',
        'vendor.qti.hardware.radio.ims@1.0',
        'vendor.qti.hardware.radio.ims@1.1',
        'vendor.qti.hardware.radio.ims@1.2',
        'vendor.qti.hardware.radio.ims@1.3',
        'vendor.qti.hardware.radio.ims@1.4',
        'vendor.qti.hardware.radio.ims@1.5',
        'vendor.qti.hardware.radio.ims@1.6',
        'vendor.qti.hardware.radio.ims@1.7',
        'vendor.qti.hardware.radio.lpa@1.0',
        'vendor.qti.hardware.radio.lpa@1.1',
        'vendor.qti.hardware.radio.qtiradio@1.0',
        'vendor.qti.hardware.radio.qtiradio@2.0',
        'vendor.qti.hardware.radio.qtiradio@2.1',
        'vendor.qti.hardware.radio.qtiradio@2.2',
        'vendor.qti.hardware.radio.qtiradio@2.3',
        'vendor.qti.hardware.radio.qtiradio@2.4',
        'vendor.qti.hardware.radio.uim@1.0',
        'vendor.qti.hardware.radio.uim@1.1',
        'vendor.qti.hardware.radio.uim@1.2',
        'vendor.qti.hardware.radio.uim_remote_client@1.0',
        'vendor.qti.hardware.radio.uim_remote_client@1.1',
        'vendor.qti.hardware.radio.uim_remote_client@1.2',
        'vendor.qti.hardware.radio.uim_remote_server@1.0',
        'vendor.qti.hardware.slmadapter@1.0',
        'vendor.qti.hardware.tui_comm@1.0',
        'vendor.qti.ims.callcapability@1.0',
        'vendor.qti.ims.callinfo@1.0',
        'vendor.qti.ims.factory@1.0',
        'vendor.qti.ims.rcsconfig@1.0',
        'vendor.qti.ims.rcsconfig@1.1',
        'vendor.qti.ims.rcsconfig@2.0',
        'vendor.qti.imsrtpservice@3.0',
        'vendor.qti.latency@2.0',
    ): lib_fixup_vendor_suffix,
}

blob_fixups = {
    # This callback performs only validated, same-length byte replacements.
    # The pinned camera already includes libcamera_sdm660_shim.so; do not use
    # .add_needed() or .fix_soname() on it, which could move program headers.
    'vendor/lib/hw/camera.sdm660.so': blob_fixup()
        .call(blob_fixup_camera, need_tmp_dir=False),
    'vendor/bin/mlipayd@1.1': blob_fixup()
        .remove_needed('vendor.xiaomi.hardware.mtdservice@1.0.so'),
    ('vendor/lib64/libmlipay.so', 'vendor/lib64/libmlipay@1.1.so'): blob_fixup()
        .remove_needed('vendor.xiaomi.hardware.mtdservice@1.0.so')
        .binary_regex_replace(b'/system/etc/firmware', b'/vendor/firmware\0\0\0\0'),
    'vendor/lib64/libwvhidl.so': blob_fixup()
        .replace_needed('libprotobuf-cpp-lite-3.9.1.so', 'libprotobuf-cpp-full-3.9.1.so')
        .add_needed('libcrypto_shim.so'),
    # libdirac imports __android_log_print without declaring its provider.
    'vendor/lib/soundfx/libdirac.so': blob_fixup()
        .add_needed('liblog.so'),
    'vendor/lib/libMiWatermark.so': blob_fixup()
        .add_needed('libmiwatermark_shim.so'),
    # Lavender 826a3bf: these exact LIBC_PRIVATE imports exist in tulip too.
    'vendor/lib/libmmcamera_faceproc.so': blob_fixup()
        .clear_symbol_version('__aeabi_memcpy')
        .clear_symbol_version('__aeabi_memset')
        .clear_symbol_version('__gnu_Unwind_Find_exidx'),
    # Tulip's imglib repeats libfastcvopt in DT_NEEDED. Preserve one entry.
    'vendor/lib/libmmcamera_imglib.so': blob_fixup()
        .call(remove_duplicate_needed, need_tmp_dir=False),
    (
        'vendor/lib/vendor.qti.hardware.fingerprint@1.0.so',
        'vendor/lib64/vendor.qti.hardware.fingerprint@1.0.so',
        'vendor/lib64/hw/fingerprint.fpc.default.so',
        'vendor/lib64/libvendor.goodix.hardware.fingerprint@1.0.so',
        'vendor/lib64/libvendor.goodix.hardware.fingerprint@1.0-service.so',
    ): blob_fixup()
        .remove_needed('libhidltransport.so')
        .remove_needed('libhwbinder.so')
        .replace_needed('libhidlbase.so', 'libhidlbase-v32.so'),
}  # fmt: skip

module = ExtractUtilsModule(
    'tulip',
    'xiaomi',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
    check_elf=True,
)
module.add_proprietary_file('proprietary-files-fm.txt').add_copy_files_guard('BOARD_HAVE_QCOM_FM', 'true')
module.add_proprietary_file('proprietary-files-ir.txt').add_copy_files_guard('BOARD_HAVE_IR', 'true')

if __name__ == '__main__':
    ExtractUtils.device(module).run()
