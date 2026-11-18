#!/bin/bash
#
# Copyright (C) 2016 The CyanogenMod Project
# Copyright (C) 2017-2020 The LineageOS Project
#
# SPDX-License-Identifier: Apache-2.0
#

set -e

export DEVICE=tulip
export VENDOR=xiaomi

MY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_ROOT="${MY_DIR}/../../.."
HELPER="${ANDROID_ROOT}/tools/extract-utils/extract_utils.sh"
if [ ! -f "${HELPER}" ]; then
    echo "Unable to find helper script at ${HELPER}"
    exit 1
fi
source "${HELPER}"

function blob_fixup() {
    case "${1}" in
        vendor/lib/hw/camera.sdm660.so)
            if ! "${PATCHELF}" --print-needed "${2}" | grep -Fxq libcamera_sdm660_shim.so; then
                "${PATCHELF}" --add-needed libcamera_sdm660_shim.so "${2}"
            fi
            ;;
        vendor/bin/mlipayd@1.1)
            "${PATCHELF}" --remove-needed vendor.xiaomi.hardware.mtdservice@1.0.so "${2}"
            ;;
        vendor/lib64/libmlipay.so | vendor/lib64/libmlipay@1.1.so)
            "${PATCHELF}" --remove-needed vendor.xiaomi.hardware.mtdservice@1.0.so "${2}"
            sed -i 's|/system/etc/firmware|/vendor/firmware\x0\x0\x0\x0|g' "${2}"
            ;;
        vendor/lib64/libwvhidl.so)
            [ -n "${2}" ] || return 0
            "${PATCHELF}" --replace-needed libprotobuf-cpp-lite-3.9.1.so libprotobuf-cpp-full-3.9.1.so "${2}"
            if ! "${PATCHELF}" --print-needed "${2}" | grep -Fxq libcrypto_shim.so; then
                "${PATCHELF}" --add-needed libcrypto_shim.so "${2}"
            fi
            ;;
    esac
}

CLEAN_VENDOR=true
KANG=
SECTION=
SRC=

while [ "${#}" -gt 0 ]; do
    case "${1}" in
        -n | --no-cleanup)
            CLEAN_VENDOR=false
            ;;
        -k | --kang)
            KANG="--kang"
            ;;
        -s | --section)
            if [ "${#}" -lt 2 ]; then
                echo "Missing argument for ${1}" >&2
                exit 1
            fi
            SECTION="${2}"
            CLEAN_VENDOR=false
            shift
            ;;
        *)
            SRC="${1}"
            ;;
    esac
    shift
done

SRC="${SRC:-adb}"

setup_vendor "${DEVICE}" "${VENDOR}" "${ANDROID_ROOT}" false "${CLEAN_VENDOR}"
extract "${MY_DIR}/proprietary-files.txt" "${SRC}" ${KANG} --section "${SECTION}"
extract "${MY_DIR}/proprietary-files-fm.txt" "${SRC}" ${KANG} --section "${SECTION}"
extract "${MY_DIR}/proprietary-files-ir.txt" "${SRC}" ${KANG} --section "${SECTION}"

"${MY_DIR}/setup-makefiles.sh"
