#!/bin/bash -x

MANAGE="/usr/local/bin/nova-manage"

function archive_deleted_rows {
    # NOTE(danms): Run this a few times to make sure that we end
    # up with nothing more to archive
    for i in `seq 30`; do
        $MANAGE $* db archive_deleted_rows --verbose --max_rows 1000
        RET=$?
        if [[ $RET -gt 1 ]]; then
            echo Archiving failed with result $RET
            return $RET
        elif [[ $RET -eq 0 ]]; then
            echo Archiving Complete
            break;
        fi
    done
}

function purge_db {
    $MANAGE db purge --all --verbose --all-cells
    RET=$?
    if [[ $RET -eq 0 ]]; then
        echo Purge successful
    else
        echo Purge failed with result $RET
        return $RET
    fi
}

BASE=${BASE:-/opt/stack}
source ${BASE}/new/devstack/functions-common
source ${BASE}/new/devstack/lib/nova
cell_conf=$(conductor_conf 1)
# NOTE(danms): We need to pass the main config to get the api db
# bits, and then also the cell config for the cell1 db (instead of
# the cell0 config that is in the main config file). Later files
# take precedence.
conf="--config-file $NOVA_CONF --config-file $cell_conf"

archive_deleted_rows $conf
purge_db

set -e
# We need to get the admin credentials to run the OSC CLIs for Placement.
set +x
source $BASE/new/devstack/openrc admin
set -x

# TODO(mriedem): Consider checking for instances in ERROR state because
# if there are any, we would expect them to retain allocations in Placement
# and therefore we don't really need to check for leaked allocations.

# Check for orphaned instance allocations in Placement which could mean
# something failed during a test run and isn't getting cleaned up properly.
echo "Looking for leaked resource provider allocations in Placement"
LEAKED_ALLOCATIONS=0
for provider in $(openstack resource provider list -c uuid -f value); do
    echo "Looking for allocations for provider $provider"
    allocations=$(openstack resource provider show --allocations $provider \
                  -c allocations -f value)
    if [[ "$allocations" != "{}" ]]; then
        echo "Resource provider has allocations:"
        openstack resource provider show --allocations $provider
        LEAKED_ALLOCATIONS=1
    fi
done

# Fail if there were any leaked allocations.
if [[ $LEAKED_ALLOCATIONS -eq 1 ]]; then
    echo "There were leaked allocations; failing."
    exit 1
fi
echo "Resource provider allocations were cleaned up properly."


# Test "nova-manage placement heal_allocations" by creating a server, deleting
# its allocations in placement, and then running heal_allocations and assert
# the allocations were healed as expected.
image_id=$(openstack image list -f value -c ID | awk 'NR==1{print $1}')
flavor_id=$(openstack flavor list -f value -c ID | awk 'NR==1{print $1}')
network_id=$(openstack network list --no-share -f value -c ID | awk 'NR==1{print $1}')

echo "Creating server for heal_allocations testing"
openstack server create --image ${image_id} --flavor ${flavor_id} \
--nic net-id=${network_id} --wait heal-allocations-test
server_id=$(openstack server show heal-allocations-test -f value -c id)

# Make sure there are allocations for the consumer.
allocations=$(openstack resource provider allocation show ${server_id} \
              -c resources -f value)
if [[ "$allocations" == "" ]]; then
    echo "No allocations found for the server."
    exit 2
fi

echo "Deleting allocations in placement for the server"
openstack resource provider allocation delete ${server_id}

# Make sure the allocations are gone.
allocations=$(openstack resource provider allocation show ${server_id} \
              -c resources -f value)
if [[ "$allocations" != "" ]]; then
    echo "Server allocations were not deleted."
    exit 2
fi

echo "Healing allocations"
nova-manage placement heal_allocations --verbose

# Make sure there are allocations for the consumer.
allocations=$(openstack resource provider allocation show ${server_id} \
              -c resources -f value)
if [[ "$allocations" == "" ]]; then
    echo "Failed to heal allocations."
    exit 2
fi

echo "Verifying online_data_migrations idempotence"
# We will re-use the server created earlier for this test. (A server needs to
# be present during the run of online_data_migrations and archiving).

# Run the online data migrations before archiving.
$MANAGE db online_data_migrations

# We need to archive the deleted marker instance used by the
# fill_virtual_interface_list online data migration in order to trigger
# creation of a new deleted marker instance.
set +e
archive_deleted_rows $conf
set -e

# Verify whether online data migrations run after archiving will succeed.
# See for more details: https://bugs.launchpad.net/nova/+bug/1824435
$MANAGE db online_data_migrations
