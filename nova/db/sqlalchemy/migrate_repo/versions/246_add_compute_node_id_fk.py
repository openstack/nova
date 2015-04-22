# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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


from migrate.changeset.constraint import ForeignKeyConstraint
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    """Add missing foreign key constraint on pci_devices.compute_node_id."""
    meta = MetaData(bind=migrate_engine)

    pci_devices = Table('pci_devices', meta, autoload=True)
    compute_nodes = Table('compute_nodes', meta, autoload=True)

    fkey = ForeignKeyConstraint(columns=[pci_devices.c.compute_node_id],
                                refcolumns=[compute_nodes.c.id])
    fkey.create()
