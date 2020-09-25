#!/bin/bash
# Source tempest to determine the build timeout configuration.
source /opt/stack/devstack/lib/tempest
source /opt/stack/devstack/openrc admin
set -x
set -e

# Now force the evacuation to the controller; we have to force to bypass the
# scheduler since we killed libvirtd which will trigger the libvirt compute
# driver to auto-disable the nova-compute service and then the ComputeFilter
# would filter out this host and we'd get NoValidHost. Normally forcing a host
# during evacuate and bypassing the scheduler is a very bad idea, but we're
# doing a negative test here.

function evacuate_and_wait_for_error() {
    local server="$1"

    echo "Forcing evacuate of ${server} to local host"
    # TODO(mriedem): Use OSC when it supports evacuate.
    nova --os-compute-api-version "2.67" evacuate --force ${server} ${CONTROLLER_HOSTNAME}
    # Wait for the instance to go into ERROR state from the failed evacuate.
    count=0
    status=$(openstack server show ${server} -f value -c status)
    while [ "${status}" != "ERROR" ]
    do
        sleep 1
        count=$((count+1))
        if [ ${count} -eq ${BUILD_TIMEOUT} ]; then
            echo "Timed out waiting for server ${server} to go to ERROR status"
            exit 4
        fi
        status=$(openstack server show ${server} -f value -c status)
    done
}

evacuate_and_wait_for_error evacuate-test
evacuate_and_wait_for_error evacuate-bfv-test
