# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
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

import copy

from oslo.serialization import jsonutils
import six

from nova import objects
from nova.objects import base
from nova.objects import fields


class PciDevicePool(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'product_id': fields.StringField(),
        'vendor_id': fields.StringField(),
        'tags': fields.DictOfNullableStringsField(),
        'count': fields.IntegerField(),
        }

    # NOTE(pmurray): before this object existed the pci device pool data was
    # stored as a dict. For backward compatibility we need to be able to read
    # it in from a dict
    @classmethod
    def from_dict(cls, value):
        pool_dict = copy.copy(value)
        pool = cls()
        pool.vendor_id = pool_dict.pop("vendor_id")
        pool.product_id = pool_dict.pop("product_id")
        pool.count = pool_dict.pop("count")
        pool.tags = {}
        pool.tags.update(pool_dict)
        return pool


class PciDevicePoolList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial verison
    #              PciDevicePool <= 1.0
    VERSION = '1.0'
    fields = {
             'objects': fields.ListOfObjectsField('PciDevicePool'),
             }
    child_versions = {
            '1.0': '1.0',
            }


def from_pci_stats(pci_stats):
    """Create and return a PciDevicePoolList from the data stored in the db,
    which can be either the serialized object, or, prior to the creation of the
    device pool objects, a simple dict or a list of such dicts.
    """
    pools = None
    if isinstance(pci_stats, six.string_types):
        try:
            pci_stats = jsonutils.loads(pci_stats)
        except (ValueError, TypeError):
            pci_stats = None
    if pci_stats:
        # Check for object-ness, or old-style storage format.
        if 'nova_object.namespace' in pci_stats:
            pools = objects.PciDevicePoolList.obj_from_primitive(pci_stats)
        else:
            # This can be either a dict or a list of dicts
            if isinstance(pci_stats, list):
                pool_list = [objects.PciDevicePool.from_dict(stat)
                             for stat in pci_stats]
            else:
                pool_list = [objects.PciDevicePool.from_dict(pci_stats)]
            pools = objects.PciDevicePoolList(objects=pool_list)
    return pools
