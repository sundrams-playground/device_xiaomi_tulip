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

setup_vendor "${DEVICE}" "${VENDOR}" "${ANDROID_ROOT}" false
write_headers
write_makefiles "${MY_DIR}/proprietary-files.txt" true

printf '\n%s\n' 'ifeq ($(BOARD_HAVE_QCOM_FM),true)' >> "${PRODUCTMK}"
write_makefiles "${MY_DIR}/proprietary-files-fm.txt" true
echo 'endif' >> "${PRODUCTMK}"

printf '\n%s\n' 'ifeq ($(BOARD_HAVE_IR),true)' >> "${PRODUCTMK}"
write_makefiles "${MY_DIR}/proprietary-files-ir.txt" true
echo 'endif' >> "${PRODUCTMK}"

write_footers
