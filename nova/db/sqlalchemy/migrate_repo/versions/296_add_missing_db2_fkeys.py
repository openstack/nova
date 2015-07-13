# Copyright 2014 IBM Corp.
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

from migrate import ForeignKeyConstraint
from sqlalchemy import MetaData, Table


DB2_FKEYS = [
    # NOTE(mriedem): Added in 216.
    {'table': 'fixed_ips',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'fixed_ips_instance_uuid_fkey'},
    {'table': 'block_device_mapping',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'block_device_mapping_instance_uuid_fkey'},
    {'table': 'instance_info_caches',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'instance_info_caches_instance_uuid_fkey'},
    {'table': 'instance_metadata',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'instance_metadata_instance_uuid_fkey'},
    {'table': 'instance_system_metadata',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'instance_system_metadata_ibfk_1'},
    {'table': 'security_group_instance_association',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'security_group_instance_association_instance_uuid_fkey'},
    {'table': 'virtual_interfaces',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'virtual_interfaces_instance_uuid_fkey'},
    {'table': 'instance_actions',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'fk_instance_actions_instance_uuid'},
    {'table': 'instance_faults',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'fk_instance_faults_instance_uuid'},
    {'table': 'migrations',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'fk_migrations_instance_uuid'},
    # NOTE(mriedem): Added in 252.
    {'table': 'instance_extra',
     'columns': ['instance_uuid'],
     'refcolumns': ['instances.uuid'],
     'name': 'fk_instance_extra_instance_uuid'}
]


def _get_refcolumns(metadata, refcolumns):
    refcolumn_objects = []
    for refcol in refcolumns:
        table, column = refcol.split('.')
        table = Table(table, metadata, autoload=True)
        refcolumn_objects.append(table.c[column])
    return refcolumn_objects


def upgrade(migrate_engine):
    if migrate_engine.name == 'ibm_db_sa':
        # create the foreign keys
        metadata = MetaData(bind=migrate_engine)
        for values in DB2_FKEYS:
            # NOTE(mriedem): We have to load all of the tables in the same
            # MetaData object for the ForeignKey object to work, so we just
            # load up the Column objects here as well dynamically.
            params = dict(name=values['name'])
            table = Table(values['table'], metadata, autoload=True)
            params['table'] = table
            params['columns'] = [table.c[col] for col in values['columns']]
            params['refcolumns'] = _get_refcolumns(metadata,
                                                   values['refcolumns'])
            fkey = ForeignKeyConstraint(**params)
            fkey.create()
