# Copyright (c) 2014 Red Hat, Inc.
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


from migrate import UniqueConstraint
from sqlalchemy import MetaData, Table, Column, String


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # Add a new column host
    compute_nodes = Table('compute_nodes', meta, autoload=True)
    shadow_compute_nodes = Table('shadow_compute_nodes', meta, autoload=True)

    # NOTE(sbauza) : Old compute nodes can report stats without this field, we
    # need to set it as nullable
    host = Column('host', String(255), nullable=True)
    if not hasattr(compute_nodes.c, 'host'):
        compute_nodes.create_column(host)
    if not hasattr(shadow_compute_nodes.c, 'host'):
        shadow_compute_nodes.create_column(host.copy())

    # NOTE(sbauza) : Populate the host field with the value from the services
    # table will be done at the ComputeNode object level when save()

    ukey = UniqueConstraint('host', 'hypervisor_hostname', table=compute_nodes,
                            name="uniq_compute_nodes0host0hypervisor_hostname")
    ukey.create()
