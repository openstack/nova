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

from oslo_config import cfg

pci_alias_opt = cfg.MultiStrOpt(
    'pci_alias',
    default=[],
    help='An alias for a PCI passthrough device requirement. This allows '
    'users to specify the alias in the extra_spec for a flavor, '
    'without needing to repeat all the PCI property requirements. For '
    'example: pci_alias = { '
    '"name": "QuickAssist", '
    '"product_id": "0443", '
    '"vendor_id": "8086", '
    '"device_type": "type-PCI" '
    '} defines an alias for the Intel QuickAssist card. (multi '
    'valued).')

pci_passthrough_whitelist_opt = cfg.MultiStrOpt(
    'pci_passthrough_whitelist',
    default=[],
    help='White list of PCI devices available to VMs. For example: '
    'pci_passthrough_whitelist = '
    '[{"vendor_id": "8086", "product_id": "0443"}]')

ALL_OPTS = [pci_alias_opt,
            pci_passthrough_whitelist_opt]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    # TODO(sfinucan): This should be moved into the PCI group and
    # oslo_config.cfg.OptGroup used
    return {'DEFAULT': ALL_OPTS}
