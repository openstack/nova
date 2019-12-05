# Copyright 2013 Nicira, Inc.
# All Rights Reserved
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

from oslo_utils import importutils

import nova.network


NOVA_DRIVER = ('nova.compute.api.SecurityGroupAPI')
NEUTRON_DRIVER = ('nova.network.security_group.neutron_driver.'
                  'SecurityGroupAPI')
DRIVER_CACHE = None  # singleton of the driver once loaded


def get_openstack_security_group_driver():
    global DRIVER_CACHE
    if DRIVER_CACHE is None:
        if is_neutron_security_groups():
            DRIVER_CACHE = importutils.import_object(NEUTRON_DRIVER)
        else:
            DRIVER_CACHE = importutils.import_object(NOVA_DRIVER)
    return DRIVER_CACHE


def is_neutron_security_groups():
    return nova.network.is_neutron()
