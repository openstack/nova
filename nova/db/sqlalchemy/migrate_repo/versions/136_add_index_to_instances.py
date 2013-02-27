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

from sqlalchemy import MetaData, Table, Index

INDEX_NAME = 'instances_host_node_deleted_idx'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    # Based on instance_get_all_host_and_node
    # from: nova/db/sqlalchemy/api.py
    index = Index(INDEX_NAME,
                  instances.c.host, instances.c.node, instances.c.deleted)
    index.create(migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    index = Index(INDEX_NAME,
                  instances.c.host, instances.c.node, instances.c.deleted)
    index.drop(migrate_engine)
