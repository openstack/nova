#!/bin/bash
# Live migration dedicated ci job will be responsible for testing different
# environments based on underlying storage, used for ephemerals.
# This hook allows to inject logic of environment reconfiguration in ci job.
# Base scenario for this would be:
#
# 1. test with all local storage (use default for volumes)
# 2. test with NFS for root + ephemeral disks
# 3. test with Ceph for root + ephemeral disks
# 4. test with Ceph for volumes and root + ephemeral disk

set -xe
cd $BASE/new/tempest

source $BASE/new/devstack/functions
source $BASE/new/devstack/functions-common
source $BASE/new/devstack/lib/nova
source $WORKSPACE/devstack-gate/functions.sh
source $BASE/new/nova/gate/live_migration/hooks/utils.sh
source $BASE/new/nova/gate/live_migration/hooks/nfs.sh
source $BASE/new/nova/gate/live_migration/hooks/ceph.sh
primary_node=$(cat /etc/nodepool/primary_node_private)
SUBNODES=$(cat /etc/nodepool/sub_nodes_private)
SERVICE_HOST=$primary_node
STACK_USER=${STACK_USER:-stack}

echo '1. test with all local storage (use default for volumes)'
echo 'NOTE: test_volume_backed_live_migration is skipped due to https://bugs.launchpad.net/nova/+bug/1524898'
echo 'NOTE: test_live_block_migration_paused is skipped due to https://bugs.launchpad.net/nova/+bug/1901739'
run_tempest "block migration test" "^.*test_live_migration(?!.*(test_volume_backed_live_migration|test_live_block_migration_paused))"

# TODO(mriedem): Run $BASE/new/nova/gate/test_evacuate.sh for local storage

#all tests bellow this line use shared storage, need to update tempest.conf
echo 'disabling block_migration in tempest'
$ANSIBLE primary --become -f 5 -i "$WORKSPACE/inventory" -m ini_file -a "dest=$BASE/new/tempest/etc/tempest.conf section=compute-feature-enabled option=block_migration_for_live_migration value=False"

echo '2. NFS testing is skipped due to setup failures with Ubuntu 16.04'
#echo '2. test with NFS for root + ephemeral disks'

#nfs_setup
#nfs_configure_tempest
#nfs_verify_setup
#run_tempest  "NFS shared storage test" "live_migration"
#nfs_teardown

# The nova-grenade-multinode job also runs resize and cold migration tests
# so we check for a grenade-only variable.
if [[ -n "$GRENADE_NEW_BRANCH" ]]; then
    echo '3. test cold migration and resize'
    run_tempest "cold migration and resize test" "test_resize_server|test_cold_migration|test_revert_cold_migration"
else
    echo '3. cold migration and resize is skipped for non-grenade jobs'
fi

echo '4. test with Ceph for root + ephemeral disks'
# Discover and set variables for the OS version so the devstack-plugin-ceph
# scripts can find the correct repository to install the ceph packages.
GetOSVersion
USE_PYTHON3=${USE_PYTHON3:-True}
prepare_ceph
GLANCE_API_CONF=${GLANCE_API_CONF:-/etc/glance/glance-api.conf}
configure_and_start_glance

configure_and_start_nova
run_tempest "Ceph nova&glance test" "^.*test_live_migration(?!.*(test_volume_backed_live_migration))"

set +e
#echo '5. test with Ceph for volumes and root + ephemeral disk'

#configure_and_start_cinder
#run_tempest "Ceph nova&glance&cinder test" "live_migration"
