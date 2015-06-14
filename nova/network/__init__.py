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

import oslo_config.cfg
from oslo_utils import importutils

_network_opts = [
    oslo_config.cfg.StrOpt('network_api_class',
                           default='nova.network.api.API',
                           help='The full class name of the '
                                'network API class to use'),
]

oslo_config.cfg.CONF.register_opts(_network_opts)


def API(skip_policy_check=False):
    network_api_class = oslo_config.cfg.CONF.network_api_class
    if 'quantumv2' in network_api_class:
        network_api_class = network_api_class.replace('quantumv2', 'neutronv2')
    cls = importutils.import_class(network_api_class)
    return cls(skip_policy_check=skip_policy_check)
