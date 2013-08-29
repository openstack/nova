# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

import jsonschema

from nova import exception
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.pci import pci_utils

from oslo.config import cfg

pci_opts = [cfg.MultiStrOpt('pci_passthrough_whitelist',
                            default=[],
                            help='White list of PCI devices available to VMs. '
                            'For example: pci_passthrough_whitelist =  '
                            '[{"vendor_id": "8086", "product_id": "0443"}]'
                            )
            ]
CONF = cfg.CONF
CONF.register_opts(pci_opts)

LOG = logging.getLogger(__name__)


_PCI_VENDOR_PATTERN = "^(hex{4})$".replace("hex", "[\da-fA-F]")
_WHITELIST_SCHEMA = {
    "type": "array",
    "items":
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "product_id": {
                "type": "string",
                "pattern": _PCI_VENDOR_PATTERN
            },
            "vendor_id": {
                "type": "string",
                "pattern": _PCI_VENDOR_PATTERN
            },
        },
        "required": ["product_id", "vendor_id"]
    }
}


class PciHostDevicesWhiteList(object):

    """White list class to decide assignable pci devices.

    Not all devices on compute node can be assigned to guest, the
    cloud administrator decides the devices that can be assigned
    based on vendor_id or product_id etc. If no white list specified,
    no device will be assignable.
    """

    def _parse_white_list_from_config(self, whitelists):
        """Parse and validate the pci whitelist from the nova config."""
        specs = []
        try:
            for jsonspecs in whitelists:
                spec = jsonutils.loads(jsonspecs)
                jsonschema.validate(spec, _WHITELIST_SCHEMA)
                specs.extend(spec)
        except Exception as e:
            raise exception.PciConfigInvalidWhitelist(reason=str(e))

        return specs

    def __init__(self, whitelist_spec=None):
        """White list constructor

        For example, followed json string specifies that devices whose
        vendor_id is '8086' and product_id is '1520' can be assigned
        to guest.
        '[{"product_id":"1520", "vendor_id":"8086"}]'

        :param whitelist_spec: A json string for a list of dictionaries,
                               each dictionary specifies the pci device
                               properties requirement.
        """
        super(PciHostDevicesWhiteList, self).__init__()
        if whitelist_spec:
            self.spec = self._parse_white_list_from_config(whitelist_spec)
        else:
            self.spec = None

    def device_assignable(self, dev):
        """Check if a device can be assigned to a guest.

        :param dev: A dictionary describing the device properties
        """
        if self.spec is None:
            return False
        return pci_utils.pci_device_prop_match(dev, self.spec)


def get_pci_devices_filter():
    return PciHostDevicesWhiteList(CONF.pci_passthrough_whitelist)
