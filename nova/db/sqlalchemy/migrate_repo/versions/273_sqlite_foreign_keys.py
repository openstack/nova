# Copyright 2014 Rackspace Hosting
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

from migrate import ForeignKeyConstraint, UniqueConstraint
from oslo_db.sqlalchemy import utils
from sqlalchemy import MetaData, schema, Table


FKEYS = [
    ('fixed_ips', 'instance_uuid', 'instances', 'uuid',
     'fixed_ips_instance_uuid_fkey'),
    ('block_device_mapping', 'instance_uuid', 'instances', 'uuid',
     'block_device_mapping_instance_uuid_fkey'),
    ('instance_info_caches', 'instance_uuid', 'instances', 'uuid',
     'instance_info_caches_instance_uuid_fkey'),
    ('instance_metadata', 'instance_uuid', 'instances', 'uuid',
     'instance_metadata_instance_uuid_fkey'),
    ('instance_system_metadata', 'instance_uuid', 'instances', 'uuid',
     'instance_system_metadata_ibfk_1'),
    ('instance_type_projects', 'instance_type_id', 'instance_types', 'id',
     'instance_type_projects_ibfk_1'),
    ('iscsi_targets', 'volume_id', 'volumes', 'id',
     'iscsi_targets_volume_id_fkey'),
    ('reservations', 'usage_id', 'quota_usages', 'id',
     'reservations_ibfk_1'),
    ('security_group_instance_association', 'instance_uuid',
     'instances', 'uuid',
     'security_group_instance_association_instance_uuid_fkey'),
    ('security_group_instance_association', 'security_group_id',
     'security_groups', 'id',
     'security_group_instance_association_ibfk_1'),
    ('virtual_interfaces', 'instance_uuid', 'instances', 'uuid',
     'virtual_interfaces_instance_uuid_fkey'),
    ('compute_nodes', 'service_id', 'services', 'id',
     'fk_compute_nodes_service_id'),
    ('instance_actions', 'instance_uuid', 'instances', 'uuid',
     'fk_instance_actions_instance_uuid'),
    ('instance_faults', 'instance_uuid', 'instances', 'uuid',
     'fk_instance_faults_instance_uuid'),
    ('migrations', 'instance_uuid', 'instances', 'uuid',
     'fk_migrations_instance_uuid'),
]

UNIQUES = [
    ('compute_nodes', 'uniq_compute_nodes0host0hypervisor_hostname',
     ['host', 'hypervisor_hostname']),
    ('fixed_ips', 'uniq_fixed_ips0address0deleted',
     ['address', 'deleted']),
    ('instance_info_caches', 'uniq_instance_info_caches0instance_uuid',
     ['instance_uuid']),
    ('instance_type_projects',
     'uniq_instance_type_projects0instance_type_id0project_id0deleted',
     ['instance_type_id', 'project_id', 'deleted']),
    ('pci_devices', 'uniq_pci_devices0compute_node_id0address0deleted',
     ['compute_node_id', 'address', 'deleted']),
    ('virtual_interfaces', 'uniq_virtual_interfaces0address0deleted',
     ['address', 'deleted']),
]


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    if migrate_engine.name == 'sqlite':
        # SQLite is also missing this one index
        if not utils.index_exists(migrate_engine, 'fixed_ips', 'address'):
            utils.add_index(migrate_engine, 'fixed_ips', 'address',
                            ['address'])

        for src_table, src_column, dst_table, dst_column, name in FKEYS:
            src_table = Table(src_table, meta, autoload=True)
            if name in set(fk.name for fk in src_table.foreign_keys):
                continue

            src_column = src_table.c[src_column]

            dst_table = Table(dst_table, meta, autoload=True)
            dst_column = dst_table.c[dst_column]

            fkey = ForeignKeyConstraint(columns=[src_column],
                                        refcolumns=[dst_column],
                                        name=name)
            fkey.create()

        # SQLAlchemy versions < 1.0.0 don't reflect unique constraints
        # for SQLite correctly causing sqlalchemy-migrate to recreate
        # some tables with missing unique constraints. Re-add some
        # potentially missing unique constraints as a workaround.
        for table_name, name, column_names in UNIQUES:
            table = Table(table_name, meta, autoload=True)
            if name in set(c.name for c in table.constraints
                           if isinstance(table, schema.UniqueConstraint)):
                continue

            uc = UniqueConstraint(*column_names, table=table, name=name)
            uc.create()
