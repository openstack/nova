# Copyright 2012 OpenStack Foundation
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

from sqlalchemy import and_, String, Column, MetaData, select, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    node = Column('node', String(length=255))

    instances.create_column(node)

    c_nodes = Table('compute_nodes', meta, autoload=True)
    services = Table('services', meta, autoload=True)

    # set instances.node = compute_nodes.hypervisor_hostname
    q = select(
            [instances.c.id, c_nodes.c.hypervisor_hostname],
            whereclause=and_(
                 instances.c.deleted != True,
                 services.c.deleted != True,
                 services.c.binary == 'nova-compute',
                 c_nodes.c.deleted != True),
            from_obj=instances.join(services,
                                    instances.c.host == services.c.host)
                              .join(c_nodes,
                                    services.c.id == c_nodes.c.service_id))
    for (instance_id, hypervisor_hostname) in q.execute():
        instances.update().where(instances.c.id == instance_id).\
                           values(node=hypervisor_hostname).\
                           execute()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    instances.drop_column('node')
