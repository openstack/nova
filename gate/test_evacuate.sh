#!/bin/bash -x

BASE=${BASE:-/opt/stack}
# Source stackrc to determine the configured VIRT_DRIVER
source ${BASE}/new/devstack/stackrc
# Source tempest to determine the build timeout configuration.
source ${BASE}/new/devstack/lib/tempest

set -e
# We need to get the admin credentials to run CLIs.
set +x
source ${BASE}/new/devstack/openrc admin
set -x

if [[ ${VIRT_DRIVER} != libvirt ]]; then
   echo "Only the libvirt driver is supported by this script"
   exit 1
fi

echo "Ensure we have at least two compute nodes"
nodenames=$(openstack hypervisor list -f value -c 'Hypervisor Hostname')
node_count=$(echo ${nodenames} | wc -w)
if [[ ${node_count} -lt 2 ]]; then
    echo "Evacuate requires at least two nodes"
    exit 2
fi

echo "Finding the subnode"
subnode=''
local_hostname=$(hostname -s)
for nodename in ${nodenames}; do
    if [[ ${local_hostname} != ${nodename} ]]; then
        subnode=${nodename}
        break
    fi
done

# Sanity check that we found the subnode.
if [[ -z ${subnode} ]]; then
    echo "Failed to find subnode from nodes: ${nodenames}"
    exit 3
fi

image_id=$(openstack image list -f value -c ID | awk 'NR==1{print $1}')
flavor_id=$(openstack flavor list -f value -c ID | awk 'NR==1{print $1}')
network_id=$(openstack network list --no-share -f value -c ID | awk 'NR==1{print $1}')

echo "Creating ephemeral test server on subnode"
openstack server create --image ${image_id} --flavor ${flavor_id} \
--nic net-id=${network_id} --availability-zone nova:${subnode} --wait evacuate-test

echo "Creating BFV test server on subnode"
# TODO(mriedem): Use OSC when it supports boot from volume where nova creates
# the root volume from an image.
nova boot --flavor ${flavor_id} --poll \
--block-device id=${image_id},source=image,dest=volume,size=1,bootindex=0,shutdown=remove \
--nic net-id=${network_id} --availability-zone nova:${subnode} evacuate-bfv-test

# Fence the subnode
echo "Stopping n-cpu, q-agt and guest domains on subnode"
$ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "systemctl stop devstack@n-cpu devstack@q-agt"
$ANSIBLE subnodes --become -f 5 -i "$WORKSPACE/inventory" -m shell -a "for domain in \$(virsh list --all --name); do  virsh destroy \$domain; done"

echo "Forcing down the subnode so we can evacuate from it"
openstack --os-compute-api-version 2.11 compute service set --down ${subnode} nova-compute

echo "Stopping libvirt on the localhost before evacuating to trigger failure"
sudo systemctl stop libvirt-bin

# Now force the evacuation to *this* host; we have to force to bypass the
# scheduler since we killed libvirtd which will trigger the libvirt compute
# driver to auto-disable the nova-compute service and then the ComputeFilter
# would filter out this host and we'd get NoValidHost. Normally forcing a host
# during evacuate and bypassing the scheduler is a very bad idea, but we're
# doing a negative test here.

function evacuate_and_wait_for_error() {
    local server="$1"

    echo "Forcing evacuate of ${server} to local host"
    # TODO(mriedem): Use OSC when it supports evacuate.
    nova --os-compute-api-version "2.67" evacuate --force ${server} ${local_hostname}
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

echo "Now restart libvirt and perform a successful evacuation"
sudo systemctl start libvirt-bin
sleep 10

# Wait for the compute service to be enabled.
count=0
status=$(openstack compute service list --host ${local_hostname} --service nova-compute -f value -c Status)
while [ "${status}" != "enabled" ]
do
    sleep 1
    count=$((count+1))
    if [ ${count} -eq 30 ]; then
        echo "Timed out waiting for local compute service to be enabled"
        exit 5
    fi
    status=$(openstack compute service list --host ${local_hostname} --service nova-compute -f value -c Status)
done

function evacuate_and_wait_for_active() {
    local server="$1"

    nova evacuate ${server}
    # Wait for the instance to go into ACTIVE state from the evacuate.
    count=0
    status=$(openstack server show ${server} -f value -c status)
    while [ "${status}" != "ACTIVE" ]
    do
        sleep 1
        count=$((count+1))
        if [ ${count} -eq ${BUILD_TIMEOUT} ]; then
            echo "Timed out waiting for server ${server} to go to ACTIVE status"
            exit 6
        fi
        status=$(openstack server show ${server} -f value -c status)
    done
}

evacuate_and_wait_for_active evacuate-test
evacuate_and_wait_for_active evacuate-bfv-test

# Make sure the servers moved.
for server in evacuate-test evacuate-bfv-test; do
    host=$(openstack server show ${server} -f value -c OS-EXT-SRV-ATTR:host)
    if [[ ${host} != ${local_hostname} ]]; then
        echo "Unexpected host ${host} for server ${server} after evacuate."
        exit 7
    fi
done

# Cleanup test servers
openstack server delete --wait evacuate-test
openstack server delete --wait evacuate-bfv-test
