#    Copyright 2017 Red Hat, Inc.
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

from sqlalchemy import MetaData, Table, Column, Integer


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for prefix in ('', 'shadow_'):
        compute_nodes = Table('%scompute_nodes' % prefix, meta, autoload=True)
        mapped = Column('mapped', Integer, default=0, nullable=True)
        if not hasattr(compute_nodes.c, 'mapped'):
            compute_nodes.create_column(mapped)
