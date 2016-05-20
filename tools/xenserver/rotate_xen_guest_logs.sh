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
syslog_tag='rotate_xen_guest_logs'

log_file_base="${log_dir}/console."

# Only delete log files older than this number of minutes
# to avoid a race where Xen creates the domain and starts
# logging before the XAPI VM start returns (and allows us
# to preserve the log file using last_dom_id)
min_logfile_age=10

# Ensure logging is setup correctly for all domains
xenstore-write /local/logconsole/@ "${log_file_base}%d"

# Grab the list of logs now to prevent a race where the domain is
# started after we get the valid last_dom_ids, but before the logs are
# deleted.  Add spaces to ensure we can do containment tests below
current_logs=$(find "$log_dir" -type f)

# Ensure the last_dom_id is set + updated for all running VMs
for vm in $(xe vm-list power-state=running --minimal | tr ',' ' '); do
    xe vm-param-set uuid=$vm other-config:last_dom_id=$(xe vm-param-get uuid=$vm param-name=dom-id)
done

# Get the last_dom_id for all VMs
valid_last_dom_ids=$(xe vm-list params=other-config --minimal | tr ';,' '\n\n' | grep last_dom_id | sed -e 's/last_dom_id: //g' | xargs)
echo "Valid dom IDs: $valid_last_dom_ids" | /usr/bin/logger -t $syslog_tag

# Remove old console files that do not correspond to valid last_dom_id's
allowed_consoles=".*console.\(${valid_last_dom_ids// /\\|}\)$"
delete_logs=`find "$log_dir" -type f -mmin +${min_logfile_age} -not -regex "$allowed_consoles"`
for log in $delete_logs; do
    if echo "$current_logs" | grep -q -w "$log"; then
        echo "Deleting: $log" | /usr/bin/logger -t $syslog_tag
        rm $log
    fi
done

# Truncate all remaining logs
for log in `find "$log_dir" -type f -regex '.*console.*' -size +${max_size_bytes}c`; do
    echo "Truncating log: $log" | /usr/bin/logger -t $syslog_tag
    tmp="$log.tmp"
    tail -c $truncated_size_bytes "$log" > "$tmp"
    mv -f "$tmp" "$log"

    # Notify xen that it needs to reload the file
    domid="${log##*.}"
    xenstore-write /local/logconsole/$domid "$log"
    xenstore-rm /local/logconsole/$domid
done
