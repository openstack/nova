# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from oslo_utils import importutils

import nova.conf

NOVA_NET_API = 'nova.network.api.API'
NEUTRON_NET_API = 'nova.network.neutronv2.api.API'


CONF = nova.conf.CONF


def is_neutron():
    """Does this configuration mean we're neutron.

    This logic exists as a separate config option
    """
    return CONF.use_neutron


def API():
    if is_neutron():
        network_api_class = NEUTRON_NET_API
    else:
        network_api_class = NOVA_NET_API

    cls = importutils.import_class(network_api_class)
    return cls()
