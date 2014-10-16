# Copyright 2013 Intel Corporation
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

""" Example of a PCI alias::

        | pci_alias = '{
        |   "name": "QuicAssist",
        |   "product_id": "0443",
        |   "vendor_id": "8086",
        |   "device_type": "ACCEL",
        |   }'

    Aliases with the same name and the same device_type are OR operation::

        | pci_alias = '{
        |   "name": "QuicAssist",
        |   "product_id": "0442",
        |   "vendor_id": "8086",
        |   "device_type": "ACCEL",
        |   }'

    These 2 aliases define a device request meaning: vendor_id is "8086" and
    product id is "0442" or "0443".

    """

import copy

import jsonschema
from oslo.config import cfg
from oslo.serialization import jsonutils
import six

from nova import exception
from nova import objects
from nova.openstack.common import log as logging
from nova.pci import utils

pci_alias_opts = [
    cfg.MultiStrOpt('pci_alias',
                    default=[],
                    help='An alias for a PCI passthrough device requirement. '
                        'This allows users to specify the alias in the '
                        'extra_spec for a flavor, without needing to repeat '
                        'all the PCI property requirements. For example: '
                        'pci_alias = '
                          '{ "name": "QuicAssist", '
                          '  "product_id": "0443", '
                          '  "vendor_id": "8086", '
                          '  "device_type": "ACCEL" '
                          '} '
                        'defines an alias for the Intel QuickAssist card. '
                        '(multi valued)'
                   )
]

PCI_NET_TAG = 'physical_network'

CONF = cfg.CONF
CONF.register_opts(pci_alias_opts)

LOG = logging.getLogger(__name__)


_ALIAS_DEV_TYPE = ['NIC', 'ACCEL', 'GPU']
_ALIAS_CAP_TYPE = ['pci']
_ALIAS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
        },
        "capability_type": {
            "type": "string",
            "enum": _ALIAS_CAP_TYPE,
        },
        "product_id": {
            "type": "string",
            "pattern": utils.PCI_VENDOR_PATTERN,
        },
        "vendor_id": {
            "type": "string",
            "pattern": utils.PCI_VENDOR_PATTERN,
        },
        "device_type": {
            "type": "string",
            "enum": _ALIAS_DEV_TYPE,
        },
    },
    "required": ["name"],
}


def _get_alias_from_config():
    """Parse and validate PCI aliases from the nova config."""
    jaliases = CONF.pci_alias
    aliases = {}  # map alias name to alias spec list
    try:
        for jsonspecs in jaliases:
            spec = jsonutils.loads(jsonspecs)
            jsonschema.validate(spec, _ALIAS_SCHEMA)
            name = spec.pop("name")
            if name not in aliases:
                aliases[name] = [spec]
            else:
                if aliases[name][0]["device_type"] == spec["device_type"]:
                    aliases[name].append(spec)
                else:
                    reason = "Device type mismatch for alias '%s'" % name
                    raise exception.PciInvalidAlias(reason=reason)

    except exception.PciInvalidAlias:
        raise
    except Exception as e:
        raise exception.PciInvalidAlias(reason=six.text_type(e))

    return aliases


def _translate_alias_to_requests(alias_spec):
    """Generate complete pci requests from pci aliases in extra_spec."""

    pci_aliases = _get_alias_from_config()

    pci_requests = []  # list of a specs dict
    alias_spec = alias_spec.replace(' ', '')
    for name, count in [spec.split(':') for spec in alias_spec.split(',')]:
        if name not in pci_aliases:
            raise exception.PciRequestAliasNotDefined(alias=name)
        else:
            request = objects.InstancePCIRequest(
                count=int(count),
                spec=copy.deepcopy(pci_aliases[name]),
                alias_name=name)
            pci_requests.append(request)
    return pci_requests


def get_pci_requests_from_flavor(flavor):
    """Get flavor's pci request.

    The pci_passthrough:alias scope in flavor extra_specs
    describes the flavor's pci requests, the key is
    'pci_passthrough:alias' and the value has format
    'alias_name_x:count, alias_name_y:count, ... '. The alias_name is
    defined in 'pci_alias' configurations.

    The flavor's requirement is translated into pci requests list,
    each entry in the list is a dictionary. The dictionary has
    three keys. The 'specs' gives the pci device properties
    requirement, the 'count' gives the number of devices, and the
    optional 'alias_name' is the corresponding alias definition name.

    Example:
    Assume alias configuration is::

        |   {'vendor_id':'8086',
        |    'device_id':'1502',
        |    'name':'alias_1'}

    The flavor extra specs includes: 'pci_passthrough:alias': 'alias_1:2'.

    The returned pci_requests are::

        | pci_requests = [{'count':2,
        |                'specs': [{'vendor_id':'8086',
        |                           'device_id':'1502'}],
        |                'alias_name': 'alias_1'}]

    :param flavor: the flavor to be checked
    :returns: a list of pci requests
    """
    pci_requests = []
    if ('extra_specs' in flavor and
            'pci_passthrough:alias' in flavor['extra_specs']):
        pci_requests = _translate_alias_to_requests(
            flavor['extra_specs']['pci_passthrough:alias'])
    return objects.InstancePCIRequests(requests=pci_requests)
