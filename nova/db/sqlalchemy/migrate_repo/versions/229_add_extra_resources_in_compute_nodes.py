# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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


from sqlalchemy import Column
from sqlalchemy import MetaData
from sqlalchemy import Table
from sqlalchemy import Text


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # Add a new column extra_resources to save extra_resources info for
    # compute nodes
    compute_nodes = Table('compute_nodes', meta, autoload=True)
    shadow_compute_nodes = Table('shadow_compute_nodes', meta, autoload=True)

    extra_resources = Column('extra_resources', Text, nullable=True)
    shadow_extra_resources = Column('extra_resources', Text, nullable=True)
    compute_nodes.create_column(extra_resources)
    shadow_compute_nodes.create_column(shadow_extra_resources)
