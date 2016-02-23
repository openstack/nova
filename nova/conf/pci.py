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
    help="""
An alias for a PCI passthrough device requirement.

This allows users to specify the alias in the extra_spec for a flavor, without
needing to repeat all the PCI property requirements.

Possible Values:

* A list of JSON values which describe the aliases. For example:

    pci_alias = {
      "name": "QuickAssist",
      "product_id": "0443",
      "vendor_id": "8086",
      "device_type": "type-PCI"
    }

  defines an alias for the Intel QuickAssist card. (multi valued). Valid key
  values are :

  * "name"
  * "product_id"
  * "vendor_id"
  * "device_type"

Services which consume this:

* nova-compute

Related options:

* None""")

pci_passthrough_whitelist_opt = cfg.MultiStrOpt(
    'pci_passthrough_whitelist',
    default=[],
    help="""
White list of PCI devices available to VMs.

Possible values:

* A JSON dictionary which describe a whitelisted PCI device. It should take
  the following format:

    ["device_id": "<id>",] ["product_id": "<id>",]
    ["address": "[[[[<domain>]:]<bus>]:][<slot>][.[<function>]]" |
     "devname": "PCI Device Name",]
    {"tag": "<tag_value>",}

  where '[' indicates zero or one occurrences, '{' indicates zero or multiple
  occurrences, and '|' mutually exclusive options. Note that any missing
  fields are automatically wildcarded. Valid examples are:

    pci_passthrough_whitelist = {"devname":"eth0",
                                 "physical_network":"physnet"}
    pci_passthrough_whitelist = {"address":"*:0a:00.*"}
    pci_passthrough_whitelist = {"address":":0a:00.",
                                 "physical_network":"physnet1"}
    pci_passthrough_whitelist = {"vendor_id":"1137",
                                 "product_id":"0071"}
    pci_passthrough_whitelist = {"vendor_id":"1137",
                                 "product_id":"0071",
                                 "address": "0000:0a:00.1",
                                 "physical_network":"physnet1"}

  The following are invalid, as they specify mutually exclusive options:

    pci_passthrough_whitelist = {"devname":"eth0",
                                 "physical_network":"physnet",
                                 "address":"*:0a:00.*"}

* A JSON list of JSON dictionaries corresponding to the above format. For
  example:

    pci_passthrough_whitelist = [{"product_id":"0001", "vendor_id":"8086"},
                                 {"product_id":"0002", "vendor_id":"8086"}]

Services which consume this:

* nova-compute

Related options:

* None""")

ALL_OPTS = [pci_alias_opt,
            pci_passthrough_whitelist_opt]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    # TODO(sfinucan): This should be moved into the PCI group and
    # oslo_config.cfg.OptGroup used
    return {'DEFAULT': ALL_OPTS}
