#!/bin/bash
# Live migration dedicated ci job will be responsible for testing different
# environments based on underlying storage, used for ephemerals.
# This hook allows to inject logic of environment reconfiguration in ci job.
# Base scenario for this would be:
# - run live-migration on env without shared storage
# - set up ceph for ephemerals, and reconfigure nova, tempest for that
# - run live-migration tests
# - remove ceph and set up nfs for ephemerals, make appropriate change in nova
# and tempest config
# - run live-migration tests

tempest tox -eall --concurrency=$TEMPEST_CONCURRENCY live_migration
