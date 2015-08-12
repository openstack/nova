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

log_file_base="${log_dir}/console."

# Ensure logging is setup correctly for all domains
xenstore-write /local/logconsole/@ "${log_file_base}%d"

# Ensure the last_dom_id is set + updated for all running VMs
for vm in $(xe vm-list power-state=running --minimal | tr ',' ' '); do
    xe vm-param-set uuid=$vm other-config:last_dom_id=$(xe vm-param-get uuid=$vm param-name=dom-id)
done

# Get the last_dom_id for all VMs
valid_last_dom_ids=$(xe vm-list params=other-config --minimal | tr ';,' '\n\n' | grep last_dom_id | sed -e 's/last_dom_id: //g' | xargs)

# Remove console files that do not correspond to valid last_dom_id's
allowed_consoles=".*console.\(${valid_last_dom_ids// /\\|}\)$"
find $log_dir -type f -not -regex $allowed_consoles -delete

# Truncate all remaining logs
for log in `find $log_dir -type f -regex '.*console.*' -size +${max_size_bytes}c`; do
    tmp="$log.tmp"
    tail -c $truncated_size_bytes $log > $tmp
    mv -f $tmp $log

    # Notify xen that it needs to reload the file
    domid=${log##*.}
    xenstore-write /local/logconsole/$domid $log
    xenstore-rm /local/logconsole/$domid
done
