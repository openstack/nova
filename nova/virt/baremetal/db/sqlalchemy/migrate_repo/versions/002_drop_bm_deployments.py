# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

from sqlalchemy import Column, Index, MetaData, Table
from sqlalchemy import Integer, String, DateTime, Boolean


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    bm_nodes = Table('bm_nodes', meta, autoload=True)

    image_path = Column('image_path', String(length=255))
    pxe_config_path = Column('pxe_config_path', String(length=255))
    deploy_key = Column('deploy_key', String(length=255))
    root_mb = Column('root_mb', Integer())
    swap_mb = Column('swap_mb', Integer())

    for c in [image_path, pxe_config_path, deploy_key, root_mb, swap_mb]:
        bm_nodes.create_column(c)

    deploy_key_idx = Index('deploy_key_idx', bm_nodes.c.deploy_key)
    deploy_key_idx.create(migrate_engine)

    bm_deployments = Table('bm_deployments', meta, autoload=True)
    bm_deployments.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    bm_nodes = Table('bm_nodes', meta, autoload=True)

    for c in ['image_path', 'pxe_config_path', 'deploy_key', 'root_mb',
              'swap_mb']:
        bm_nodes.drop_column(c)

    bm_deployments = Table('bm_deployments', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('bm_node_id', Integer),
        Column('key', String(length=255)),
        Column('image_path', String(length=255)),
        Column('pxe_config_path', String(length=255)),
        Column('root_mb', Integer),
        Column('swap_mb', Integer),
        mysql_engine='InnoDB',
    )
    bm_deployments.create()
