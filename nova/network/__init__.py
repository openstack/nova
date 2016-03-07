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
from oslo_log import log as logging
from oslo_utils import importutils

from nova.i18n import _LW

LOG = logging.getLogger(__name__)

NOVA_NET_API = 'nova.network.api.API'
NEUTRON_NET_API = 'nova.network.neutronv2.api.API'

_network_opts = [
    oslo_config.cfg.StrOpt('network_api_class',
                           default=NOVA_NET_API,
                           help='DEPRECATED: The full class name of the '
                                'network API class to use. ``use_neutron`` '
                                'should be used instead.',
                           deprecated_for_removal=True),
    oslo_config.cfg.BoolOpt('use_neutron',
                            default=False,
                            help="""
Whether to use Neutron or Nova Network as the back end for networking.
Defaults to False (indicating Nova network). Set to True to use neutron.
""")

]

oslo_config.cfg.CONF.register_opts(_network_opts)


def is_neutron():
    """Does this configuration mean we're neutron.

    This logic exists as a separate config option
    """
    legacy_class = oslo_config.cfg.CONF.network_api_class
    use_neutron = oslo_config.cfg.CONF.use_neutron

    if legacy_class not in (NEUTRON_NET_API, NOVA_NET_API):
        # Someone actually used this option, this gets a pass for now,
        # but will just go away once deleted.
        return None
    elif legacy_class == NEUTRON_NET_API and not use_neutron:
        # If they specified neutron via class, we should respect that
        LOG.warn(_LW("Config mismatch. The network_api_class specifies %s, "
                     "however use_neutron is not set to True. Using Neutron "
                     "networking for now, however please set use_neutron to "
                     "True in your configuration as network_api_class is "
                     "deprecated and will be removed."), legacy_class)
        return True
    elif use_neutron:
        return True
    else:
        return False


def API(skip_policy_check=False):
    if is_neutron() is None:
        network_api_class = oslo_config.cfg.CONF.network_api_class
    elif is_neutron():
        network_api_class = NEUTRON_NET_API
    else:
        network_api_class = NOVA_NET_API

    cls = importutils.import_class(network_api_class)
    return cls(skip_policy_check=skip_policy_check)
