# Copyright 2014 Intel Corporation
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

#
# See blueprint backportable-db-migrations-icehouse
# http://lists.openstack.org/pipermail/openstack-dev/2013-March/006827.html

from sqlalchemy import MetaData, Table, Column, Integer


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    # Add a new column to store PCI device numa node
    pci_devices = Table('pci_devices', meta, autoload=True)
    shadow_pci_devices = Table('shadow_pci_devices', meta, autoload=True)

    numa_node = Column('numa_node', Integer, default=None)
    if not hasattr(pci_devices.c, 'numa_node'):
        pci_devices.create_column(numa_node)
    if not hasattr(shadow_pci_devices.c, 'numa_node'):
        shadow_pci_devices.create_column(numa_node.copy())
