#!/bin/sh

# FILE: /etc/udev/scripts/iscsidev.sh

BUS=${1}
HOST=${BUS%%:*}

[ -e /sys/class/iscsi_host ] || exit 1

file="/sys/class/iscsi_host/host${HOST}/device/session*/iscsi_session*/session*/targetname"

target_name=$(cat ${file})

# This is not an open-scsi drive
if [ -z "${target_name}" ]; then
   exit 1
fi

echo "${target_name##*:}"
