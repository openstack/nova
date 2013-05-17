# Copyright 2013 Rackspace Hosting
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

from sqlalchemy import Index, MetaData, Table


TABLE_NAME = 'compute_node_stats'
IDX_NAME = 'compute_node_stats_node_id_and_deleted_idx'


def upgrade(migrate_engine):
    """Add an index to make the scheduler lookups of compute_nodes and joined
    compute_node_stats more efficient.
    """
    meta = MetaData(bind=migrate_engine)
    cn_stats = Table(TABLE_NAME, meta, autoload=True)
    idx = Index(IDX_NAME, cn_stats.c.compute_node_id, cn_stats.c.deleted)
    idx.create(migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    cn_stats = Table(TABLE_NAME, meta, autoload=True)
    idx = Index(IDX_NAME, cn_stats.c.compute_node_id, cn_stats.c.deleted)
    idx.drop(migrate_engine)
