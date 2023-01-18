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

pci_group = cfg.OptGroup(
    name='pci',
    title='PCI passthrough options')

pci_opts = [
    cfg.MultiStrOpt('alias',
        default=[],
        deprecated_name='pci_alias',
        deprecated_group='DEFAULT',
        help="""
An alias for a PCI passthrough device requirement.

This allows users to specify the alias in the extra specs for a flavor, without
needing to repeat all the PCI property requirements.

This should be configured for the ``nova-api`` service and, assuming you wish
to use move operations, for each ``nova-compute`` service.

Possible Values:

* A dictionary of JSON values which describe the aliases. For example::

    alias = {
      "name": "QuickAssist",
      "product_id": "0443",
      "vendor_id": "8086",
      "device_type": "type-PCI",
      "numa_policy": "required"
    }

  This defines an alias for the Intel QuickAssist card. (multi valued). Valid
  key values are :

  ``name``
    Name of the PCI alias.

  ``product_id``
    Product ID of the device in hexadecimal.

  ``vendor_id``
    Vendor ID of the device in hexadecimal.

  ``device_type``
    Type of PCI device. Valid values are: ``type-PCI``, ``type-PF`` and
    ``type-VF``. Note that ``"device_type": "type-PF"`` **must** be specified
    if you wish to passthrough a device that supports SR-IOV in its entirety.

  ``numa_policy``
    Required NUMA affinity of device. Valid values are: ``legacy``,
    ``preferred`` and ``required``.

  ``resource_class``
    The optional Placement resource class name that is used
    to track the requested PCI devices in Placement. It can be a standard
    resource class from the ``os-resource-classes`` lib. Or it can be an
    arbitrary string. If it is an non-standard resource class then Nova will
    normalize it to a proper Placement resource class by
    making it upper case, replacing any consecutive character outside of
    ``[A-Z0-9_]`` with a single '_', and prefixing the name with ``CUSTOM_`` if
    not yet prefixed. The maximum allowed length is 255 character including the
    prefix. If ``resource_class`` is not provided Nova will generate it from
    ``vendor_id`` and ``product_id`` values of the alias in the form of
    ``CUSTOM_PCI_{vendor_id}_{product_id}``. The ``resource_class`` requested
    in the alias is matched against the ``resource_class`` defined in the
    ``[pci]device_spec``. This field can only be used only if
    ``[filter_scheduler]pci_in_placement`` is enabled.

  ``traits``
    An optional comma separated list of Placement trait names requested to be
    present on the resource provider that fulfills this alias. Each trait can
    be a standard trait from ``os-traits`` lib or it can be an arbitrary
    string. If it is a non-standard trait then Nova will normalize the
    trait name by making it upper case, replacing any consecutive character
    outside of  ``[A-Z0-9_]`` with a single '_', and  prefixing the name
    with ``CUSTOM_`` if not yet prefixed. The maximum allowed length of a
    trait name is 255 character including the prefix. Every trait in
    ``traits`` requested in the alias ensured to be in the list of traits
    provided in the ``traits`` field of the ``[pci]device_spec`` when
    scheduling the request. This field can only be used only if
    ``[filter_scheduler]pci_in_placement`` is enabled.

* Supports multiple aliases by repeating the option (not by specifying
  a list value)::

    alias = {
      "name": "QuickAssist-1",
      "product_id": "0443",
      "vendor_id": "8086",
      "device_type": "type-PCI",
      "numa_policy": "required"
    }
    alias = {
      "name": "QuickAssist-2",
      "product_id": "0444",
      "vendor_id": "8086",
      "device_type": "type-PCI",
      "numa_policy": "required"
    }
"""),
    cfg.MultiStrOpt('device_spec',
        default=[],
        deprecated_opts=[
            cfg.DeprecatedOpt('passthrough_whitelist', group='pci'),
            cfg.DeprecatedOpt('pci_passthrough_whitelist', group='DEFAULT'),
        ],
        help="""
Specify the PCI devices available to VMs.

Possible values:

* A JSON dictionary which describe a PCI device. It should take
  the following format::

    ["vendor_id": "<id>",] ["product_id": "<id>",]
    ["address": "[[[[<domain>]:]<bus>]:][<slot>][.[<function>]]" |
     "devname": "<name>",]
    {"<tag>": "<tag_value>",}

  Where ``[`` indicates zero or one occurrences, ``{`` indicates zero or
  multiple occurrences, and ``|`` mutually exclusive options. Note that any
  missing fields are automatically wildcarded.

  Valid key values are :

  ``vendor_id``
    Vendor ID of the device in hexadecimal.

  ``product_id``
    Product ID of the device in hexadecimal.

  ``address``
    PCI address of the device. Both traditional glob style and regular
    expression syntax is supported. Please note that the address fields are
    restricted to the following maximum values:

    * domain - 0xFFFF
    * bus - 0xFF
    * slot - 0x1F
    * function - 0x7

  ``devname``
    Device name of the device (for e.g. interface name). Not all PCI devices
    have a name.

  ``<tag>``
    Additional ``<tag>`` and ``<tag_value>`` used for specifying PCI devices.
    Supported ``<tag>`` values are :

    - ``physical_network``
    - ``trusted``
    - ``remote_managed`` - a VF is managed remotely by an off-path networking
      backend. May have boolean-like string values case-insensitive values:
      "true" or "false". By default, "false" is assumed for all devices.
      Using this option requires a networking service backend capable of
      handling those devices. PCI devices are also required to have a PCI
      VPD capability with a card serial number (either on a VF itself on
      its corresponding PF), otherwise they will be ignored and not
      available for allocation.
    - ``resource_class`` - optional Placement resource class name to be used
      to track the matching PCI devices in Placement when [pci]device_spec is
      True. It can be a standard resource class from the
      ``os-resource-classes`` lib. Or can be any string. In that case Nova will
      normalize it to a proper Placement resource class by making it upper
      case, replacing any consecutive character outside of ``[A-Z0-9_]`` with a
      single '_', and prefixing the name with ``CUSTOM_`` if not yet prefixed.
      The maximum allowed length is 255 character including the prefix.
      If ``resource_class`` is not provided Nova will generate it from the PCI
      device's ``vendor_id`` and ``product_id`` in the form of
      ``CUSTOM_PCI_{vendor_id}_{product_id}``.
      The ``resource_class`` can be requested from a ``[pci]alias``
    - ``traits`` - optional comma separated list of Placement trait names to
      report on the resource provider that will represent the matching PCI
      device. Each trait can be a standard trait from ``os-traits`` lib or can
      be any string. If it is not a standard trait then Nova will normalize the
      trait name by making it upper case, replacing any consecutive character
      outside of  ``[A-Z0-9_]`` with a single '_', and  prefixing the name with
      ``CUSTOM_`` if not yet prefixed. The maximum allowed length of a trait
      name is 255 character including the prefix.
      Any trait from ``traits`` can be requested from a ``[pci]alias``.


  Valid examples are::

    device_spec = {"devname":"eth0",
                   "physical_network":"physnet"}
    device_spec = {"address":"*:0a:00.*"}
    device_spec = {"address":":0a:00.",
                   "physical_network":"physnet1"}
    device_spec = {"vendor_id":"1137",
                   "product_id":"0071"}
    device_spec = {"vendor_id":"1137",
                   "product_id":"0071",
                   "address": "0000:0a:00.1",
                   "physical_network":"physnet1"}
    device_spec = {"address":{"domain": ".*",
                              "bus": "02", "slot": "01",
                              "function": "[2-7]"},
                   "physical_network":"physnet1"}
    device_spec = {"address":{"domain": ".*",
                              "bus": "02", "slot": "0[1-2]",
                              "function": ".*"},
                   "physical_network":"physnet1"}
    device_spec = {"devname": "eth0", "physical_network":"physnet1",
                   "trusted": "true"}
    device_spec = {"vendor_id":"a2d6",
                   "product_id":"15b3",
                   "remote_managed": "true"}
    device_spec = {"vendor_id":"a2d6",
                   "product_id":"15b3",
                   "address": "0000:82:00.0",
                   "physical_network":"physnet1",
                   "remote_managed": "true"}
    device_spec = {"vendor_id":"1002",
                   "product_id":"6929",
                   "address": "0000:82:00.0",
                   "resource_class": "PGPU",
                   "traits": "HW_GPU_API_VULKAN,my-awesome-gpu"}

  The following are invalid, as they specify mutually exclusive options::

    device_spec = {"devname":"eth0",
                   "physical_network":"physnet",
                   "address":"*:0a:00.*"}

  The following example is invalid because it specifies the ``remote_managed``
  tag for a PF - it will result in an error during config validation at the
  Nova Compute service startup::

    device_spec = {"address": "0000:82:00.0",
                   "product_id": "a2d6",
                   "vendor_id": "15b3",
                   "physical_network": null,
                   "remote_managed": "true"}

* A JSON list of JSON dictionaries corresponding to the above format. For
  example::

    device_spec = [{"product_id":"0001", "vendor_id":"8086"},
                   {"product_id":"0002", "vendor_id":"8086"}]
"""),
    cfg.BoolOpt('report_in_placement',
                default=False,
                help="""
Enable PCI resource inventory reporting to Placement. If it is enabled then the
nova-compute service will report PCI resource inventories to Placement
according to the [pci]device_spec configuration and the PCI devices reported
by the hypervisor. Once it is enabled it cannot be disabled any more. In a
future release the default of this config will be change to True.

Related options:

* [pci]device_spec: to define which PCI devices nova are allowed to track and
  assign to guests.
"""),
]


def register_opts(conf):
    conf.register_group(pci_group)
    conf.register_opts(pci_opts, group=pci_group)


def list_opts():
    return {pci_group: pci_opts}
