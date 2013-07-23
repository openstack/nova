# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Mirantis Inc.
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
#


from sqlalchemy import Index, MetaData, Table


INDEXES_DATA = {
    # table_name: ((idx_1, (c1, c2,)), (idx2, (c1, c2,)), ...)
    'agent_builds': (
        ('agent_builds_hypervisor_os_arch_idx',
         ('hypervisor', 'os', 'architecture'),),
    ),
    'aggregate_metadata': (
        ('aggregate_metadata_key_idx', ('key',),),
    ),
    'block_device_mapping': (
        ('block_device_mapping_instance_uuid_idx', ('instance_uuid',),),
        ('block_device_mapping_instance_uuid_device_name_idx',
         ('instance_uuid', 'device_name',),),
        ('block_device_mapping_instance_uuid_volume_id_idx',
         ('instance_uuid', 'volume_id',)),
        ('snapshot_id', ('snapshot_id',)),
        ('volume_id', ('volume_id',)),
    ),
    'bw_usage_cache': (
        ('bw_usage_cache_uuid_start_period_idx',
         ('uuid', 'start_period',)),
    ),
    'certificates': (
        ('certificates_project_id_deleted_idx', ('project_id', 'deleted')),
        ('certificates_user_id_deleted_idx', ('user_id', 'deleted',)),
    ),
    'compute_node_stats': (
        ('ix_compute_node_stats_compute_node_id', ('compute_node_id',)),
    ),
    'consoles': (
        ('consoles_instance_uuid_idx', ('instance_uuid',)),
    ),
    'dns_domains': (
        ('dns_domains_domain_deleted_idx', ('domain', 'deleted',)),
        ('project_id', ('project_id',)),
    ),
    'fixed_ips': (
        ('address', ('address',)),
        ('fixed_ips_host_idx', ('host',)),
        ('fixed_ips_network_id_host_deleted_idx',
         ('network_id', 'host', 'deleted',)),
        ('fixed_ips_address_reserved_network_id_deleted_idx',
         ('address', 'reserved', 'network_id', 'deleted',)),
        ('network_id', ('network_id',)),
        ('fixed_ips_virtual_interface_id_fkey', ('virtual_interface_id',)),
        ('fixed_ips_instance_uuid_fkey', ('instance_uuid',)),
    ),
    'floating_ips': (
        ('fixed_ip_id', ('fixed_ip_id',)),
        ('floating_ips_host_idx', ('host',)),
        ('floating_ips_project_id_idx', ('project_id',)),
        ('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
         ('pool', 'deleted', 'fixed_ip_id', 'project_id',)),
    ),
    'instance_group_member': (
        ('instance_group_member_instance_idx', ('instance_id',)),
    ),
    'instance_group_metadata': (
        ('instance_instance_group_metadata_key_idx', ('key',)),
    ),
    'instance_group_policy': (
        ('instance_instance_group_policy_policy_idx', ('policy',)),
    ),
    'instance_faults': (
        ('instance_faults_instance_uuid_deleted_created_at_idx',
         ('instance_uuid', 'deleted', 'created_at',)),
    ),
    'instance_id_mappings': (
        ('ix_instance_id_mappings_uuid', ('uuid',)),
    ),
    'instance_type_extra_specs': (
        ('instance_type_extra_specs_instance_type_id_key_idx',
         ('instance_type_id', 'key',)),
    ),
    'instance_system_metadata': (
        ('instance_uuid', ('instance_uuid',)),
    ),
    'instance_metadata': (
        ('instance_metadata_instance_uuid_idx', ('instance_uuid',)),
    ),
    'instance_type_projects': (
        ('instance_type_id', ('instance_type_id',)),
    ),
    'instances': (
        ('uuid', ('uuid',)),
    ),
    'iscsi_targets': (
        ('iscsi_targets_host_idx', ('host',)),
        ('iscsi_targets_volume_id_fkey', ('volume_id',)),
        ('iscsi_targets_host_volume_id_deleted_idx',
         ('host', 'volume_id', 'deleted',)),
    ),
    'networks': (
        ('networks_bridge_deleted_idx', ('bridge', 'deleted',)),
        ('networks_host_idx', ('host',)),
        ('networks_project_id_deleted_idx', ('project_id', 'deleted',)),
        ('networks_uuid_project_id_deleted_idx',
         ('uuid', 'project_id', 'deleted',)),
        ('networks_vlan_deleted_idx', ('vlan', 'deleted',)),
        ('networks_cidr_v6_idx', ('cidr_v6',)),
    ),
    'reservations': (
        ('ix_reservations_project_id', ('project_id',)),
        ('usage_id', ('usage_id',)),
    ),
    'security_group_instance_association': (
        ('security_group_instance_association_instance_uuid_idx',
         ('instance_uuid',)),
    ),
    'quota_classes': (
        ('ix_quota_classes_class_name', ('class_name',)),
    ),
    'quota_usages': (
        ('ix_quota_usages_project_id', ('project_id',)),
    ),
    'virtual_interfaces': (
        ('virtual_interfaces_network_id_idx', ('network_id',)),
        ('virtual_interfaces_instance_uuid_fkey', ('instance_uuid',)),
    ),
    'volumes': (
        ('volumes_instance_uuid_idx', ('instance_uuid',)),
    ),
    'task_log': (
        ('ix_task_log_period_beginning', ('period_beginning',)),
        ('ix_task_log_host', ('host',)),
        ('ix_task_log_period_ending', ('period_ending',)),
    ),
}


def upgrade(migrate_engine):
    if migrate_engine.name != "sqlite":
        return

    meta = MetaData()
    meta.bind = migrate_engine

    for table_name, indexes in INDEXES_DATA.iteritems():
        table = Table(table_name, meta, autoload=True)

        for index_name, columns in indexes:
            Index(
                index_name,
                *[getattr(table.c, col) for col in columns]
            ).create(migrate_engine)


def downgrade(migrate_engine):
    if migrate_engine.name != "sqlite":
        return

    meta = MetaData()
    meta.bind = migrate_engine

    for table_name, indexes in INDEXES_DATA.iteritems():
        table = Table(table_name, meta, autoload=True)

        for index_name, columns in indexes:
            Index(
                index_name,
                *[getattr(table.c, col) for col in columns]
            ).drop(migrate_engine)
