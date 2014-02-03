# Copyright 2010 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Possible states for xen resource pools.

A pool may be 'created', in which case the admin has triggered its
creation, but the underlying hypervisor pool has not actually being set up
yet. A pool may be 'changing', meaning that the underlying hypervisor
pool is being setup. A pool may be 'active', in which case the underlying
hypervisor pool is up and running. A pool may be 'dismissed' when it has
no hosts and it has been deleted. A pool may be in 'error' in all other
cases.
A 'created' pool becomes 'changing' during the first request of
adding a host. During a 'changing' status no other requests will be accepted;
this is to allow the hypervisor layer to instantiate the underlying pool
without any potential race condition that may incur in master/slave-based
configurations. The pool goes into the 'active' state when the underlying
pool has been correctly instantiated.
All other operations (e.g. add/remove hosts) that succeed will keep the
pool in the 'active' state. If a number of continuous requests fail,
an 'active' pool goes into an 'error' state. To recover from such a state,
admin intervention is required. Currently an error state is irreversible,
that is, in order to recover from it a pool must be deleted.
"""

CREATED = 'created'
CHANGING = 'changing'
ACTIVE = 'active'
ERROR = 'error'
DISMISSED = 'dismissed'

# Metadata keys
KEY = 'operational_state'
POOL_FLAG = 'hypervisor_pool'


def is_hv_pool(metadata):
    """Checks if aggregate is a hypervisor_pool."""
    return POOL_FLAG in metadata.keys()
