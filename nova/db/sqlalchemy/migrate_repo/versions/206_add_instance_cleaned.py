# Copyright 2013 Rackspace Australia
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

from sqlalchemy import Column, Index, Integer, MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    shadow_instances = Table('shadow_instances', meta, autoload=True)

    cleaned_column = Column('cleaned', Integer, default=0)
    instances.create_column(cleaned_column)
    shadow_instances.create_column(cleaned_column.copy())

    cleaned_index = Index('instances_host_deleted_cleaned_idx',
                          instances.c.host, instances.c.deleted,
                          instances.c.cleaned)
    cleaned_index.create(migrate_engine)

    migrate_engine.execute(instances.update().
                           where(instances.c.deleted > 0).
                           values(cleaned=1))
    migrate_engine.execute(shadow_instances.update().
                           where(shadow_instances.c.deleted > 0).
                           values(cleaned=1))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    instances.columns.cleaned.drop()

    # NOTE(mikal): some engines remove this index when the column is
    # removed (sqlite for example). Instead of hardcoding that
    # behaviour we just try to remove the index and ignore the failure
    # if there is one.
    try:
        instances = Table('instances', meta, autoload=True)
        cleaned_index = Index('instances_host_deleted_cleaned_idx',
                              instances.c.host, instances.c.deleted)
        cleaned_index.drop(migrate_engine)
    except Exception:
        pass

    shadow_instances = Table('shadow_instances', meta, autoload=True)
    shadow_instances.columns.cleaned.drop()
