# Copyright 2014 Red Hat, Inc.
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


from sqlalchemy import MetaData, Table, Column, DateTime, Integer, String, \
    ForeignKey


def upgrade(migrate_engine):
    """Remove the instance_group_metadata table."""
    meta = MetaData(bind=migrate_engine)

    if migrate_engine.has_table('instance_group_metadata'):
        group_metadata = Table('instance_group_metadata', meta, autoload=True)
        group_metadata.drop()

    if migrate_engine.has_table('shadow_instance_group_metadata'):
        shadow_group_metadata = Table('shadow_instance_group_metadata', meta,
                                      autoload=True)
        shadow_group_metadata.drop()


def downgrade(migrate_engine):
    """Revert removal of the instance_group_metadata table."""
    meta = MetaData(bind=migrate_engine)
    Table('instance_groups', meta, autoload=True)
    Table('shadow_instance_groups', meta, autoload=True)

    if not migrate_engine.has_table('instance_group_metadata'):
        group_metadata = Table('instance_group_metadata', meta,
            Column('created_at', DateTime),
            Column('updated_at', DateTime),
            Column('deleted_at', DateTime),
            Column('deleted', Integer),
            Column('id', Integer, primary_key=True, nullable=False),
            Column('key', String(length=255)),
            Column('value', String(length=255)),
            Column('group_id', Integer, ForeignKey('instance_groups.id'),
                   nullable=False),
            mysql_engine='InnoDB',
            mysql_charset='utf8',
            )
        group_metadata.create()
    if not migrate_engine.has_table('shadow_instance_group_metadata'):
        shadow_group_metadata = Table('shadow_instance_group_metadata', meta,
            Column('created_at', DateTime),
            Column('updated_at', DateTime),
            Column('deleted_at', DateTime),
            Column('deleted', Integer),
            Column('id', Integer, primary_key=True, nullable=False),
            Column('key', String(length=255)),
            Column('value', String(length=255)),
            Column('group_id', Integer,
                   ForeignKey('shadow_instance_groups.id'),
                   nullable=False),
            mysql_engine='InnoDB',
            mysql_charset='utf8',
            )
        shadow_group_metadata.create()
