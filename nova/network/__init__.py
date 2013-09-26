# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import oslo.config.cfg

# Importing full names to not pollute the namespace and cause possible
# collisions with use of 'from nova.network import <foo>' elsewhere.
import nova.openstack.common.importutils

import sys
from nova import context
from nova.openstack.common import log as logging
LOG = logging.getLogger(__name__)

_network_opts = [
    oslo.config.cfg.StrOpt('network_api_class',
                           default='nova.network.api.API',
                           help='The full class name of the '
                                'network API class to use'),
    oslo.config.cfg.StrOpt('pre_defined_network',
                           default=None,
                           help='Name of pre-defined network used on this node'),
]

oslo.config.cfg.CONF.register_opts(_network_opts)


def API():
    importutils = nova.openstack.common.importutils
    network_api_class = oslo.config.cfg.CONF.network_api_class
    cls = importutils.import_class(network_api_class)
    return cls()

def get_pre_defined_network(pre_defined_network=None):
    if not pre_defined_network:
        pre_defined_network = oslo.config.cfg.CONF.pre_defined_network

    if not pre_defined_network:
        LOG.error(_("Pre-defined network required, but not specified"))
        sys.exit(1)

    return pre_defined_network
