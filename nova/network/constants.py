# Copyright 2013 UnitedStack Inc.
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

# Port fields

BINDING_PROFILE = 'binding:profile'
BINDING_HOST_ID = 'binding:host_id'
RESOURCE_REQUEST = 'resource_request'
REQUEST_GROUPS = 'request_groups'
NUMA_POLICY = 'numa_affinity_policy'

# Binding profile fields

MIGRATING_ATTR = 'migrating_to'
ALLOCATION = 'allocation'

# Core extensions

DNS_INTEGRATION = 'dns-integration'
MULTI_PROVIDER = 'multi-provider'
FIP_PORT_DETAILS = 'fip-port-details'
PORT_BINDING = 'binding'
PORT_BINDING_EXTENDED = 'binding-extended'
SUBSTR_PORT_FILTERING = 'ip-substring-filtering'
SEGMENT = 'segment'
RESOURCE_REQUEST_GROUPS = 'port-resource-request-groups'

# Third-party extensions

VNIC_INDEX = 'vnic-index'  # this is provided by the vmware_nsx project

# Search fields

NET_EXTERNAL = 'router:external'

# Misc

DEFAULT_SECGROUP = 'default'
L3_NETWORK_TYPES = ['vxlan', 'gre', 'geneve']
