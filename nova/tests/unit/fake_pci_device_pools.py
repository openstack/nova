# Copyright 2014 IBM Corp.
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

from nova.objects import pci_device_pool


# This represents the format that PCI device pool info was stored in the DB
# before this info was made into objects.
fake_pool_dict = {
        'product_id': 'fake-product',
        'vendor_id': 'fake-vendor',
        'numa_node': 1,
        't1': 'v1',
        't2': 'v2',
        'count': 2,
        }

fake_pool = pci_device_pool.PciDevicePool(count=5,
                                          product_id='foo',
                                          vendor_id='bar',
                                          numa_node=0,
                                          tags={'t1': 'v1', 't2': 'v2'})
fake_pool_primitive = fake_pool.obj_to_primitive()

fake_pool_list = pci_device_pool.PciDevicePoolList(objects=[fake_pool])
fake_pool_list_primitive = fake_pool_list.obj_to_primitive()
