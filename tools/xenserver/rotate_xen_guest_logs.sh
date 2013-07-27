#!/bin/bash
set -eux

# Script to rotate console logs
#
# Should be run on Dom0, with cron, every minute:
# * * * * * /root/rotate_xen_guest_logs.sh
#
# Should clear out the guest logs on every boot
# because the domain ids may get re-used for a
# different tenant after the reboot
#
# /var/log/xen/guest should be mounted into a
# small loopback device to stop any guest being
# able to fill dom0 file system

log_dir="/var/log/xen/guest"
kb=1024
max_size_bytes=$(($kb*$kb))
truncated_size_bytes=$((5*$kb))
list_domains=/opt/xensource/bin/list_domains

log_file_base="${log_dir}/console."
tmp_file_base="${log_dir}/tmp.console."

# Ensure logging is setup correctly for all domains
xenstore-write /local/logconsole/@ "${log_file_base}%d"

# Move logs we want to keep
domains=$($list_domains | sed '/^id*/d' | sed 's/|.*|.*$//g' | xargs)
for i in $domains; do
    log="${log_file_base}$i"
    tmp="${tmp_file_base}$i"
    mv $log $tmp || true
done

# Delete all console logs,
# mostly to remove logs from recently killed domains
rm -f ${log_dir}/console.*

# Reload domain list, in case it changed
# (note we may have just deleted a new console log)
domains=$($list_domains | sed '/^id*/d' | sed 's/|.*|.*$//g' | xargs)
for i in $domains; do
    log="${log_file_base}$i"
    tmp="${tmp_file_base}$i"

    if [ -e "$tmp" ]; then
        size=$(stat -c%s "$tmp")

        # Trim the log if required
        if [ "$size" -gt "$max_size_bytes" ]; then
            tail -c $truncated_size_bytes $tmp > $log || true
        else
            mv $tmp $log || true
        fi
    fi

    # Notify xen that it needs to reload the file
    xenstore-write /local/logconsole/$i $log
    xenstore-rm /local/logconsole/$i
done

# Delete all the tmp files
rm -f ${tmp_file_base}* || true
