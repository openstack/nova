# Copyright 2014 Rackspace Hosting
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


from oslo_db.sqlalchemy import utils


INDEXES = [
    ('block_device_mapping', 'snapshot_id', ['snapshot_id']),
    ('block_device_mapping', 'volume_id', ['volume_id']),
    ('dns_domains', 'dns_domains_project_id_idx', ['project_id']),
    ('fixed_ips', 'network_id', ['network_id']),
    ('fixed_ips', 'fixed_ips_instance_uuid_fkey', ['instance_uuid']),
    ('fixed_ips', 'fixed_ips_virtual_interface_id_fkey',
     ['virtual_interface_id']),
    ('floating_ips', 'fixed_ip_id', ['fixed_ip_id']),
    ('iscsi_targets', 'iscsi_targets_volume_id_fkey', ['volume_id']),
    ('virtual_interfaces', 'virtual_interfaces_network_id_idx',
     ['network_id']),
    ('virtual_interfaces', 'virtual_interfaces_instance_uuid_fkey',
     ['instance_uuid']),
]


def ensure_index_exists(migrate_engine, table_name, index_name, column_names):
    if not utils.index_exists(migrate_engine, table_name, index_name):
        utils.add_index(migrate_engine, table_name, index_name, column_names)


def ensure_index_removed(migrate_engine, table_name, index_name):
    if utils.index_exists(migrate_engine, table_name, index_name):
        utils.drop_index(migrate_engine, table_name, index_name)


def upgrade(migrate_engine):
    """Add indexes missing on SQLite and PostgreSQL."""

    # PostgreSQL and SQLite namespace indexes at the database level, whereas
    # MySQL namespaces indexes at the table level. Unfortunately, some of
    # the missing indexes in PostgreSQL and SQLite have conflicting names
    # that MySQL allowed.

    if migrate_engine.name in ('sqlite', 'postgresql'):
        for table_name, index_name, column_names in INDEXES:
            ensure_index_exists(migrate_engine, table_name, index_name,
                                column_names)
    elif migrate_engine.name == 'mysql':
        # Rename some indexes with conflicting names
        ensure_index_removed(migrate_engine, 'dns_domains', 'project_id')
        ensure_index_exists(migrate_engine, 'dns_domains',
                            'dns_domains_project_id_idx', ['project_id'])

        ensure_index_removed(migrate_engine, 'virtual_interfaces',
                             'network_id')
        ensure_index_exists(migrate_engine, 'virtual_interfaces',
                            'virtual_interfaces_network_id_idx',
                            ['network_id'])
