# Copyright 2015 Red Hat Inc
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

from sqlalchemy import MetaData, Table, Column, String, Index


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    # Add a new column to store PCI device parent address
    pci_devices = Table('pci_devices', meta, autoload=True)
    shadow_pci_devices = Table('shadow_pci_devices', meta, autoload=True)

    parent_addr = Column('parent_addr', String(12), nullable=True)

    if not hasattr(pci_devices.c, 'parent_addr'):
        pci_devices.create_column(parent_addr)
    if not hasattr(shadow_pci_devices.c, 'parent_addr'):
        shadow_pci_devices.create_column(parent_addr.copy())

    # Create index
    parent_index = Index('ix_pci_devices_compute_node_id_parent_addr_deleted',
                         pci_devices.c.compute_node_id,
                         pci_devices.c.parent_addr,
                         pci_devices.c.deleted)
    parent_index.create(migrate_engine)
