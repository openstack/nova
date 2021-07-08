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

from migrate.changeset import UniqueConstraint
from oslo_log import log as logging
import sqlalchemy as sa
from sqlalchemy import dialects
from sqlalchemy.ext import compiler
from sqlalchemy import types as sqla_types

from nova.db import types
from nova.objects import keypair

LOG = logging.getLogger(__name__)


def Inet():
    return sa.String(length=43).with_variant(
        dialects.postgresql.INET(), 'postgresql',
    )


def InetSmall():
    return sa.String(length=39).with_variant(
        dialects.postgresql.INET(), 'postgresql',
    )


# We explicitly name many of our foreignkeys for MySQL so they match Havana
@compiler.compiles(sa.ForeignKeyConstraint, 'postgresql')
def process(element, compiler, **kw):
    element.name = None
    return compiler.visit_foreign_key_constraint(element, **kw)


def _create_shadow_tables(migrate_engine):
    meta = sa.MetaData(migrate_engine)
    meta.reflect(migrate_engine)
    table_names = list(meta.tables.keys())

    meta.bind = migrate_engine

    for table_name in table_names:
        # Skip tables that are not soft-deletable
        if table_name in (
            'tags',
            'resource_providers',
            'inventories',
            'allocations',
            'resource_provider_aggregates',
            'console_auth_tokens',
        ):
            continue

        table = sa.Table(table_name, meta, autoload=True)

        columns = []
        for column in table.columns:
            column_copy = None

            # NOTE(boris-42): BigInteger is not supported by sqlite, so after
            # copy it will have NullType. The other types that are used in Nova
            # are supported by sqlite
            if isinstance(column.type, sqla_types.NullType):
                column_copy = sa.Column(
                    column.name, sa.BigInteger(), default=0,
                )

            if table_name == 'instances' and column.name == 'locked_by':
                enum = sa.Enum(
                    'owner', 'admin', name='shadow_instances0locked_by',
                )
                column_copy = sa.Column(column.name, enum)

            # TODO(stephenfin): Fix these various bugs in a follow-up

            # 244_increase_user_id_length_volume_usage_cache; this
            # alteration should apply to shadow tables also

            if table_name == 'volume_usage_cache' and column.name == 'user_id':
                # nullable should be True
                column_copy = sa.Column('user_id', sa.String(36))

            # 247_nullable_mismatch; these alterations should apply to shadow
            # tables also

            if table_name == 'quota_usages' and column.name == 'resources':
                # nullable should be False
                column_copy = sa.Column('resource', sa.String(length=255))

            if table_name == 'pci_devices':
                if column.name == 'deleted':
                    # nullable should be True
                    column_copy = sa.Column(
                        'deleted', sa.Integer, default=0, nullable=False,
                    )

                if column.name == 'product_id':
                    # nullable should be False
                    column_copy = sa.Column('product_id', sa.String(4))

                if column.name == 'vendor_id':
                    # nullable should be False
                    column_copy = sa.Column('vendor_id', sa.String(4))

                if column.name == 'dev_type':
                    # nullable should be False
                    column_copy = sa.Column('dev_type', sa.String(8))

            # 280_add_nullable_false_to_keypairs_name; this should apply to the
            # shadow table also

            if table_name == 'key_pairs' and column.name == 'name':
                # nullable should be False
                column_copy = sa.Column('name', sa.String(length=255))

            # NOTE(stephenfin): By default, 'sqlalchemy.Enum' will issue a
            # 'CREATE TYPE' command on PostgreSQL, even if the type already
            # exists. We work around this by using the PostgreSQL-specific
            # 'sqlalchemy.dialects.postgresql.ENUM' type and setting
            # 'create_type' to 'False'. See [1] for more information.
            #
            # [1] https://stackoverflow.com/a/28894354/613428
            if migrate_engine.name == 'postgresql':
                if table_name == 'key_pairs' and column.name == 'type':
                    enum = dialects.postgresql.ENUM(
                        'ssh', 'x509', name='keypair_types', create_type=False)
                    column_copy = sa.Column(
                        column.name, enum, nullable=False,
                        server_default=keypair.KEYPAIR_TYPE_SSH)
                elif (
                    table_name == 'migrations' and
                    column.name == 'migration_type'
                ):
                    enum = dialects.postgresql.ENUM(
                        'migration', 'resize', 'live-migration', 'evacuation',
                        name='migration_type', create_type=False)
                    column_copy = sa.Column(column.name, enum, nullable=True)

            if column_copy is None:
                column_copy = column.copy()

            columns.append(column_copy)

        shadow_table = sa.Table(
            'shadow_' + table_name, meta, *columns, mysql_engine='InnoDB',
        )

        try:
            shadow_table.create()
        except Exception:
            LOG.info(repr(shadow_table))
            LOG.exception('Exception while creating table.')
            raise

    # TODO(stephenfin): Fix these various bugs in a follow-up

    # 252_add_instance_extra_table; we don't create indexes for shadow tables
    # in general and these should be removed

    table = sa.Table('shadow_instance_extra', meta, autoload=True)
    idx = sa.Index('shadow_instance_extra_idx', table.c.instance_uuid)
    idx.create(migrate_engine)

    # 373_migration_uuid; we should't create indexes for shadow tables

    table = sa.Table('shadow_migrations', meta, autoload=True)
    idx = sa.Index('shadow_migrations_uuid', table.c.uuid, unique=True)
    idx.create(migrate_engine)


def upgrade(migrate_engine):
    meta = sa.MetaData()
    meta.bind = migrate_engine

    agent_builds = sa.Table('agent_builds', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('hypervisor', sa.String(length=255)),
        sa.Column('os', sa.String(length=255)),
        sa.Column('architecture', sa.String(length=255)),
        sa.Column('version', sa.String(length=255)),
        sa.Column('url', sa.String(length=255)),
        sa.Column('md5hash', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index(
            'agent_builds_hypervisor_os_arch_idx',
              'hypervisor', 'os', 'architecture'),
        UniqueConstraint(
            'hypervisor', 'os', 'architecture', 'deleted',
            name='uniq_agent_builds0hypervisor0os0architecture0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_hosts = sa.Table('aggregate_hosts', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(length=255)),
        sa.Column(
            'aggregate_id', sa.Integer, sa.ForeignKey('aggregates.id'),
            nullable=False),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'host', 'aggregate_id', 'deleted',
            name='uniq_aggregate_hosts0host0aggregate_id0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_metadata = sa.Table('aggregate_metadata', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'aggregate_id', sa.Integer, sa.ForeignKey('aggregates.id'),
            nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('deleted', sa.Integer),
        sa.Index('aggregate_metadata_key_idx', 'key'),
        sa.Index('aggregate_metadata_value_idx', 'value'),
        UniqueConstraint(
            'aggregate_id', 'key', 'deleted',
            name='uniq_aggregate_metadata0aggregate_id0key0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregates = sa.Table('aggregates', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Column('uuid', sa.String(36)),
        sa.Index('aggregate_uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    allocations = sa.Table('allocations', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('resource_provider_id', sa.Integer, nullable=False),
        sa.Column('consumer_id', sa.String(36), nullable=False),
        sa.Column('resource_class_id', sa.Integer, nullable=False),
        sa.Column('used', sa.Integer, nullable=False),
        sa.Index(
            'allocations_resource_provider_class_used_idx',
            'resource_provider_id', 'resource_class_id', 'used'),
        sa.Index('allocations_consumer_id_idx', 'consumer_id'),
        sa.Index('allocations_resource_class_id_idx', 'resource_class_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    block_device_mapping = sa.Table('block_device_mapping', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('device_name', sa.String(length=255), nullable=True),
        sa.Column('delete_on_termination', sa.Boolean),
        sa.Column('snapshot_id', sa.String(length=36), nullable=True),
        sa.Column('volume_id', sa.String(length=36), nullable=True),
        sa.Column('volume_size', sa.Integer),
        sa.Column('no_device', sa.Boolean),
        sa.Column('connection_info', types.MediumText()),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid',
                name='block_device_mapping_instance_uuid_fkey')),
        sa.Column('deleted', sa.Integer),
        sa.Column('source_type', sa.String(length=255), nullable=True),
        sa.Column('destination_type', sa.String(length=255), nullable=True),
        sa.Column('guest_format', sa.String(length=255), nullable=True),
        sa.Column('device_type', sa.String(length=255), nullable=True),
        sa.Column('disk_bus', sa.String(length=255), nullable=True),
        sa.Column('boot_index', sa.Integer),
        sa.Column('image_id', sa.String(length=36), nullable=True),
        sa.Column('tag', sa.String(255)),
        sa.Column('attachment_id', sa.String(36), nullable=True),
        sa.Column('uuid', sa.String(36), nullable=True),
        sa.Column('volume_type', sa.String(255), nullable=True),
        sa.Index('snapshot_id', 'snapshot_id'),
        sa.Index('volume_id', 'volume_id'),
        sa.Index('block_device_mapping_instance_uuid_idx', 'instance_uuid'),
        sa.Index(
            'block_device_mapping_instance_uuid_device_name_idx',
            'instance_uuid', 'device_name'),
        sa.Index(
            'block_device_mapping_instance_uuid_volume_id_idx',
            'instance_uuid', 'volume_id'),
        UniqueConstraint('uuid', name='uniq_block_device_mapping0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    bw_usage_cache = sa.Table('bw_usage_cache', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('start_period', sa.DateTime, nullable=False),
        sa.Column('last_refreshed', sa.DateTime),
        sa.Column('bw_in', sa.BigInteger),
        sa.Column('bw_out', sa.BigInteger),
        sa.Column('mac', sa.String(length=255)),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column('last_ctr_in', sa.BigInteger()),
        sa.Column('last_ctr_out', sa.BigInteger()),
        sa.Column('deleted', sa.Integer),
        sa.Index(
            'bw_usage_cache_uuid_start_period_idx',
            'uuid', 'start_period'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    cells = sa.Table('cells', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('api_url', sa.String(length=255)),
        sa.Column('weight_offset', sa.Float),
        sa.Column('weight_scale', sa.Float),
        sa.Column('name', sa.String(length=255)),
        sa.Column('is_parent', sa.Boolean),
        sa.Column('deleted', sa.Integer),
        sa.Column('transport_url', sa.String(length=255), nullable=False),
        UniqueConstraint(
            'name', 'deleted',
            name='uniq_cells0name0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    certificates = sa.Table('certificates', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('file_name', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index(
            'certificates_project_id_deleted_idx',
            'project_id', 'deleted'),
        sa.Index('certificates_user_id_deleted_idx', 'user_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    compute_nodes = sa.Table('compute_nodes', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('service_id', sa.Integer, nullable=True),
        sa.Column('vcpus', sa.Integer, nullable=False),
        sa.Column('memory_mb', sa.Integer, nullable=False),
        sa.Column('local_gb', sa.Integer, nullable=False),
        sa.Column('vcpus_used', sa.Integer, nullable=False),
        sa.Column('memory_mb_used', sa.Integer, nullable=False),
        sa.Column('local_gb_used', sa.Integer, nullable=False),
        sa.Column('hypervisor_type', types.MediumText(), nullable=False),
        sa.Column('hypervisor_version', sa.Integer, nullable=False),
        sa.Column('cpu_info', types.MediumText(), nullable=False),
        sa.Column('disk_available_least', sa.Integer),
        sa.Column('free_ram_mb', sa.Integer),
        sa.Column('free_disk_gb', sa.Integer),
        sa.Column('current_workload', sa.Integer),
        sa.Column('running_vms', sa.Integer),
        sa.Column('hypervisor_hostname', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Column('host_ip', InetSmall()),
        sa.Column('supported_instances', sa.Text),
        sa.Column('pci_stats', sa.Text, nullable=True),
        sa.Column('metrics', sa.Text, nullable=True),
        sa.Column('extra_resources', sa.Text, nullable=True),
        sa.Column('stats', sa.Text, default='{}'),
        sa.Column('numa_topology', sa.Text, nullable=True),
        sa.Column('host', sa.String(255), nullable=True),
        sa.Column('ram_allocation_ratio', sa.Float, nullable=True),
        sa.Column('cpu_allocation_ratio', sa.Float, nullable=True),
        sa.Column('uuid', sa.String(36), nullable=True),
        sa.Column('disk_allocation_ratio', sa.Float, nullable=True),
        sa.Column('mapped', sa.Integer, default=0, nullable=True),
        sa.Index('compute_nodes_uuid_idx', 'uuid', unique=True),
        UniqueConstraint(
            'host', 'hypervisor_hostname', 'deleted',
            name='uniq_compute_nodes0host0hypervisor_hostname0deleted',
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    console_auth_tokens = sa.Table('console_auth_tokens', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False),
        sa.Column('console_type', sa.String(255), nullable=False),
        sa.Column('host', sa.String(255), nullable=False),
        sa.Column('port', sa.Integer, nullable=False),
        sa.Column('internal_access_path', sa.String(255)),
        sa.Column('instance_uuid', sa.String(36), nullable=False),
        sa.Column('expires', sa.Integer, nullable=False),
        sa.Column('access_url_base', sa.String(255), nullable=True),
        sa.Index('console_auth_tokens_instance_uuid_idx', 'instance_uuid'),
        sa.Index('console_auth_tokens_host_expires_idx', 'host', 'expires'),
        sa.Index('console_auth_tokens_token_hash_idx', 'token_hash'),
        sa.Index(
            'console_auth_tokens_token_hash_instance_uuid_idx',
            'token_hash', 'instance_uuid'),
        UniqueConstraint(
            'token_hash', name='uniq_console_auth_tokens0token_hash'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    console_pools = sa.Table('console_pools', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('address', InetSmall()),
        sa.Column('username', sa.String(length=255)),
        sa.Column('password', sa.String(length=255)),
        sa.Column('console_type', sa.String(length=255)),
        sa.Column('public_hostname', sa.String(length=255)),
        sa.Column('host', sa.String(length=255)),
        sa.Column('compute_host', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'host', 'console_type', 'compute_host', 'deleted',
            name='uniq_console_pools0host0console_type0compute_host0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    consoles = sa.Table('consoles', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('instance_name', sa.String(length=255)),
        sa.Column('password', sa.String(length=255)),
        sa.Column('port', sa.Integer),
        sa.Column('pool_id', sa.Integer, sa.ForeignKey('console_pools.id')),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='consoles_instance_uuid_fkey')),
        sa.Column('deleted', sa.Integer),
        sa.Index('consoles_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    dns_domains = sa.Table('dns_domains', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Boolean),
        sa.Column(
            'domain', sa.String(length=255), primary_key=True, nullable=False),
        sa.Column('scope', sa.String(length=255)),
        sa.Column('availability_zone', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Index('dns_domains_domain_deleted_idx', 'domain', 'deleted'),
        sa.Index('dns_domains_project_id_idx', 'project_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    fixed_ips = sa.Table('fixed_ips', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('address', InetSmall()),
        sa.Column('network_id', sa.Integer),
        sa.Column('allocated', sa.Boolean),
        sa.Column('leased', sa.Boolean),
        sa.Column('reserved', sa.Boolean),
        sa.Column('virtual_interface_id', sa.Integer),
        sa.Column('host', sa.String(length=255)),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='fixed_ips_instance_uuid_fkey'),
        ),
        sa.Column('deleted', sa.Integer),
        sa.Index('network_id', 'network_id'),
        sa.Index('address', 'address'),
        sa.Index('fixed_ips_instance_uuid_fkey', 'instance_uuid'),
        sa.Index(
            'fixed_ips_virtual_interface_id_fkey',
            'virtual_interface_id'),
        sa.Index('fixed_ips_host_idx', 'host'),
        sa.Index(
            'fixed_ips_network_id_host_deleted_idx', 'network_id',
            'host', 'deleted'),
        sa.Index(
            'fixed_ips_address_reserved_network_id_deleted_idx',
            'address', 'reserved',
            'network_id', 'deleted'),
        sa.Index(
            'fixed_ips_deleted_allocated_idx',
            'address', 'deleted', 'allocated'),
        sa.Index(
            'fixed_ips_deleted_allocated_updated_at_idx',
              'deleted', 'allocated', 'updated_at'),
        UniqueConstraint(
            'address', 'deleted',
            name='uniq_fixed_ips0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    floating_ips = sa.Table('floating_ips', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('address', InetSmall()),
        sa.Column('fixed_ip_id', sa.Integer),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('host', sa.String(length=255)),
        sa.Column('auto_assigned', sa.Boolean),
        sa.Column('pool', sa.String(length=255)),
        sa.Column('interface', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index('fixed_ip_id', 'fixed_ip_id'),
        sa.Index('floating_ips_host_idx', 'host'),
        sa.Index('floating_ips_project_id_idx', 'project_id'),
        sa.Index(
            'floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
            'pool', 'deleted', 'fixed_ip_id', 'project_id'),
        UniqueConstraint(
            'address', 'deleted',
            name='uniq_floating_ips0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_faults = sa.Table('instance_faults', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='fk_instance_faults_instance_uuid')),
        sa.Column('code', sa.Integer, nullable=False),
        sa.Column('message', sa.String(length=255)),
        sa.Column('details', types.MediumText()),
        sa.Column('host', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index('instance_faults_host_idx', 'host'),
        sa.Index(
            'instance_faults_instance_uuid_deleted_created_at_idx',
            'instance_uuid', 'deleted', 'created_at'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_id_mappings = sa.Table('instance_id_mappings', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column('deleted', sa.Integer),
        sa.Index('ix_instance_id_mappings_uuid', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_info_caches = sa.Table('instance_info_caches', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('network_info', types.MediumText()),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid',
                name='instance_info_caches_instance_uuid_fkey'),
            nullable=False),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'instance_uuid',
            name='uniq_instance_info_caches0instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    groups = sa.Table('instance_groups', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Integer),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255)),
        UniqueConstraint(
            'uuid', 'deleted',
            name='uniq_instance_groups0uuid0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_policy = sa.Table('instance_group_policy', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Integer),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('policy', sa.String(length=255)),
        sa.Column(
            'group_id', sa.Integer, sa.ForeignKey('instance_groups.id'),
            nullable=False),
        sa.Index('instance_group_policy_policy_idx', 'policy'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_member = sa.Table('instance_group_member', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Integer),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('instance_id', sa.String(length=255)),
        sa.Column(
            'group_id', sa.Integer, sa.ForeignKey('instance_groups.id'),
            nullable=False),
        sa.Index(
            'instance_group_member_instance_idx',
            'instance_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_metadata = sa.Table('instance_metadata', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('key', sa.String(length=255)),
        sa.Column('value', sa.String(length=255)),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='instance_metadata_instance_uuid_fkey'),
            nullable=True),
        sa.Column('deleted', sa.Integer),
        sa.Index('instance_metadata_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_system_metadata = sa.Table('instance_system_metadata', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='instance_system_metadata_ibfk_1'),
            nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index('instance_uuid', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    # TODO(stephenfin): Remove this table since it has been moved to the API DB
    instance_type_extra_specs = sa.Table('instance_type_extra_specs', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'instance_type_id', sa.Integer, sa.ForeignKey('instance_types.id'),
            nullable=False),
        sa.Column('key', sa.String(length=255)),
        sa.Column('value', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index(
            'instance_type_extra_specs_instance_type_id_key_idx',
            'instance_type_id', 'key'),
        UniqueConstraint(
            'instance_type_id', 'key', 'deleted',
            name='uniq_instance_type_extra_specs0instance_type_id0key0deleted'
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    # TODO(stephenfin): Remove this table since it has been moved to the API DB
    instance_type_projects = sa.Table('instance_type_projects', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'instance_type_id', sa.Integer,
            sa.ForeignKey(
                'instance_types.id', name='instance_type_projects_ibfk_1'),
            nullable=False),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'instance_type_id', 'project_id', 'deleted',
            name='uniq_instance_type_projects0instance_type_id0project_id'
            '0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    # TODO(stephenfin): Remove this table since it has been moved to the API DB
    instance_types = sa.Table('instance_types', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('name', sa.String(length=255)),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('memory_mb', sa.Integer, nullable=False),
        sa.Column('vcpus', sa.Integer, nullable=False),
        sa.Column('swap', sa.Integer, nullable=False),
        sa.Column('vcpu_weight', sa.Integer),
        sa.Column('flavorid', sa.String(length=255)),
        sa.Column('rxtx_factor', sa.Float),
        sa.Column('root_gb', sa.Integer),
        sa.Column('ephemeral_gb', sa.Integer),
        sa.Column('disabled', sa.Boolean),
        sa.Column('is_public', sa.Boolean),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'name', 'deleted',
            name='uniq_instance_types0name0deleted'),
        UniqueConstraint(
            'flavorid', 'deleted',
            name='uniq_instance_types0flavorid0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instances = sa.Table('instances', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('internal_id', sa.Integer),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('image_ref', sa.String(length=255)),
        sa.Column('kernel_id', sa.String(length=255)),
        sa.Column('ramdisk_id', sa.String(length=255)),
        sa.Column('launch_index', sa.Integer),
        sa.Column('key_name', sa.String(length=255)),
        sa.Column('key_data', types.MediumText()),
        sa.Column('power_state', sa.Integer),
        sa.Column('vm_state', sa.String(length=255)),
        sa.Column('memory_mb', sa.Integer),
        sa.Column('vcpus', sa.Integer),
        sa.Column('hostname', sa.String(length=255)),
        sa.Column('host', sa.String(length=255)),
        sa.Column('user_data', types.MediumText()),
        sa.Column('reservation_id', sa.String(length=255)),
        sa.Column('launched_at', sa.DateTime),
        sa.Column('terminated_at', sa.DateTime),
        sa.Column('display_name', sa.String(length=255)),
        sa.Column('display_description', sa.String(length=255)),
        sa.Column('availability_zone', sa.String(length=255)),
        sa.Column('locked', sa.Boolean),
        sa.Column('os_type', sa.String(length=255)),
        sa.Column('launched_on', types.MediumText()),
        sa.Column('instance_type_id', sa.Integer),
        sa.Column('vm_mode', sa.String(length=255)),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('architecture', sa.String(length=255)),
        sa.Column('root_device_name', sa.String(length=255)),
        sa.Column('access_ip_v4', InetSmall()),
        sa.Column('access_ip_v6', InetSmall()),
        sa.Column('config_drive', sa.String(length=255)),
        sa.Column('task_state', sa.String(length=255)),
        sa.Column('default_ephemeral_device', sa.String(length=255)),
        sa.Column('default_swap_device', sa.String(length=255)),
        sa.Column('progress', sa.Integer),
        sa.Column('auto_disk_config', sa.Boolean),
        sa.Column('shutdown_terminate', sa.Boolean),
        sa.Column('disable_terminate', sa.Boolean),
        sa.Column('root_gb', sa.Integer),
        sa.Column('ephemeral_gb', sa.Integer),
        sa.Column('cell_name', sa.String(length=255)),
        sa.Column('node', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Column(
            'locked_by',
            sa.Enum('owner', 'admin', name='instances0locked_by')),
        sa.Column('cleaned', sa.Integer, default=0),
        sa.Column('ephemeral_key_uuid', sa.String(36)),
        # NOTE(danms): This column originally included default=False. We
        # discovered in bug #1862205 that this will attempt to rewrite
        # the entire instances table with that value, which can time out
        # for large data sets (and does not even abort).
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column('hidden', sa.Boolean(create_constraint=False)),
        sa.Index('uuid', 'uuid', unique=True),
        sa.Index('instances_reservation_id_idx', 'reservation_id'),
        sa.Index(
            'instances_terminated_at_launched_at_idx',
            'terminated_at', 'launched_at'),
        sa.Index(
            'instances_task_state_updated_at_idx',
            'task_state', 'updated_at'),
        sa.Index('instances_uuid_deleted_idx', 'uuid', 'deleted'),
        sa.Index('instances_host_node_deleted_idx', 'host', 'node', 'deleted'),
        sa.Index(
            'instances_host_deleted_cleaned_idx',
            'host', 'deleted', 'cleaned'),
        sa.Index('instances_project_id_deleted_idx', 'project_id', 'deleted'),
        sa.Index('instances_deleted_created_at_idx', 'deleted', 'created_at'),
        sa.Index('instances_project_id_idx', 'project_id'),
        sa.Index(
            'instances_updated_at_project_id_idx',
            'updated_at', 'project_id'),
        UniqueConstraint('uuid', name='uniq_instances0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_actions = sa.Table('instance_actions', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('action', sa.String(length=255)),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='fk_instance_actions_instance_uuid')),
        sa.Column('request_id', sa.String(length=255)),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('start_time', sa.DateTime),
        sa.Column('finish_time', sa.DateTime),
        sa.Column('message', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Index('instance_uuid_idx', 'instance_uuid'),
        sa.Index('request_id_idx', 'request_id'),
        sa.Index(
            'instance_actions_instance_uuid_updated_at_idx',
            'instance_uuid', 'updated_at'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_actions_events = sa.Table('instance_actions_events', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('event', sa.String(length=255)),
        sa.Column(
            'action_id', sa.Integer, sa.ForeignKey('instance_actions.id')),
        sa.Column('start_time', sa.DateTime),
        sa.Column('finish_time', sa.DateTime),
        sa.Column('result', sa.String(length=255)),
        sa.Column('traceback', sa.Text),
        sa.Column('deleted', sa.Integer),
        sa.Column('host', sa.String(255)),
        sa.Column('details', sa.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_extra = sa.Table('instance_extra', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Integer),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='instance_extra_instance_uuid_fkey'),
            nullable=False),
        sa.Column('numa_topology', sa.Text, nullable=True),
        sa.Column('pci_requests', sa.Text, nullable=True),
        sa.Column('flavor', sa.Text, nullable=True),
        sa.Column('vcpu_model', sa.Text, nullable=True),
        sa.Column('migration_context', sa.Text, nullable=True),
        sa.Column('keypairs', sa.Text, nullable=True),
        sa.Column('device_metadata', sa.Text, nullable=True),
        sa.Column('trusted_certs', sa.Text, nullable=True),
        sa.Column('vpmems', sa.Text, nullable=True),
        sa.Column('resources', sa.Text, nullable=True),
        sa.Index('instance_extra_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    inventories = sa.Table('inventories', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('resource_provider_id', sa.Integer, nullable=False),
        sa.Column('resource_class_id', sa.Integer, nullable=False),
        sa.Column('total', sa.Integer, nullable=False),
        sa.Column('reserved', sa.Integer, nullable=False),
        sa.Column('min_unit', sa.Integer, nullable=False),
        sa.Column('max_unit', sa.Integer, nullable=False),
        sa.Column('step_size', sa.Integer, nullable=False),
        sa.Column('allocation_ratio', sa.Float, nullable=False),
        sa.Index(
            'inventories_resource_provider_id_idx', 'resource_provider_id'),
        sa.Index(
            'inventories_resource_class_id_idx', 'resource_class_id'),
        sa.Index(
            'inventories_resource_provider_resource_class_idx',
            'resource_provider_id', 'resource_class_id'),
        UniqueConstraint(
            'resource_provider_id', 'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    key_pairs = sa.Table('key_pairs', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('fingerprint', sa.String(length=255)),
        sa.Column('public_key', types.MediumText()),
        sa.Column('deleted', sa.Integer),
        sa.Column(
            'type', sa.Enum('ssh', 'x509', name='keypair_types'),
            nullable=False, server_default=keypair.KEYPAIR_TYPE_SSH),
        UniqueConstraint(
            'user_id', 'name', 'deleted',
            name='uniq_key_pairs0user_id0name0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    migrations = sa.Table('migrations', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('source_compute', sa.String(length=255)),
        sa.Column('dest_compute', sa.String(length=255)),
        sa.Column('dest_host', sa.String(length=255)),
        sa.Column('status', sa.String(length=255)),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid', name='fk_migrations_instance_uuid')),
        sa.Column('old_instance_type_id', sa.Integer),
        sa.Column('new_instance_type_id', sa.Integer),
        sa.Column('source_node', sa.String(length=255)),
        sa.Column('dest_node', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        sa.Column(
            'migration_type',
            sa.Enum(
                'migration', 'resize', 'live-migration', 'evacuation',
                name='migration_type'),
            nullable=True),
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column(
            'hidden', sa.Boolean(create_constraint=False), default=False),
        sa.Column('memory_total', sa.BigInteger, nullable=True),
        sa.Column('memory_processed', sa.BigInteger, nullable=True),
        sa.Column('memory_remaining', sa.BigInteger, nullable=True),
        sa.Column('disk_total', sa.BigInteger, nullable=True),
        sa.Column('disk_processed', sa.BigInteger, nullable=True),
        sa.Column('disk_remaining', sa.BigInteger, nullable=True),
        sa.Column('uuid', sa.String(36)),
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column(
            'cross_cell_move', sa.Boolean(create_constraint=False),
            default=False),
        sa.Column('user_id', sa.String(255), nullable=True),
        sa.Column('project_id', sa.String(255), nullable=True),
        sa.Index('migrations_uuid', 'uuid', unique=True),
        sa.Index(
            'migrations_instance_uuid_and_status_idx',
            'deleted', 'instance_uuid', 'status'),
        sa.Index('migrations_updated_at_idx', 'updated_at'),
        # mysql-specific index by leftmost 100 chars.  (mysql gets angry if the
        # index key length is too long.)
        sa.Index(
            'migrations_by_host_nodes_and_status_idx',
            'deleted', 'source_compute', 'dest_compute', 'source_node',
            'dest_node', 'status',
            mysql_length={
                'source_compute': 100,
                'dest_compute': 100,
                'source_node': 100,
                'dest_node': 100,
            }),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    networks = sa.Table('networks', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('injected', sa.Boolean),
        sa.Column('cidr', Inet()),
        sa.Column('netmask', InetSmall()),
        sa.Column('bridge', sa.String(length=255)),
        sa.Column('gateway', InetSmall()),
        sa.Column('broadcast', InetSmall()),
        sa.Column('dns1', InetSmall()),
        sa.Column('vlan', sa.Integer),
        sa.Column('vpn_public_address', InetSmall()),
        sa.Column('vpn_public_port', sa.Integer),
        sa.Column('vpn_private_address', InetSmall()),
        sa.Column('dhcp_start', InetSmall()),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('host', sa.String(length=255)),
        sa.Column('cidr_v6', Inet()),
        sa.Column('gateway_v6', InetSmall()),
        sa.Column('label', sa.String(length=255)),
        sa.Column('netmask_v6', InetSmall()),
        sa.Column('bridge_interface', sa.String(length=255)),
        sa.Column('multi_host', sa.Boolean),
        sa.Column('dns2', InetSmall()),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column('priority', sa.Integer),
        sa.Column('rxtx_base', sa.Integer),
        sa.Column('deleted', sa.Integer),
        sa.Column('mtu', sa.Integer),
        sa.Column('dhcp_server', types.IPAddress),
        # NOTE(stephenfin): These were originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column(
            'enable_dhcp', sa.Boolean(create_constraint=False), default=True),
        sa.Column(
            'share_address', sa.Boolean(create_constraint=False),
            default=False),
        sa.Index('networks_host_idx', 'host'),
        sa.Index('networks_cidr_v6_idx', 'cidr_v6'),
        sa.Index('networks_bridge_deleted_idx', 'bridge', 'deleted'),
        sa.Index('networks_project_id_deleted_idx', 'project_id', 'deleted'),
        sa.Index(
            'networks_uuid_project_id_deleted_idx',
            'uuid', 'project_id', 'deleted'),
        sa.Index('networks_vlan_deleted_idx', 'vlan', 'deleted'),
        UniqueConstraint('vlan', 'deleted', name='uniq_networks0vlan0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    pci_devices = sa.Table('pci_devices', meta,
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('deleted', sa.Integer, default=0, nullable=True),
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column(
            'compute_node_id', sa.Integer,
            sa.ForeignKey(
                'compute_nodes.id', name='pci_devices_compute_node_id_fkey'),
            nullable=False),
        sa.Column('address', sa.String(12), nullable=False),
        sa.Column('product_id', sa.String(4), nullable=False),
        sa.Column('vendor_id', sa.String(4), nullable=False),
        sa.Column('dev_type', sa.String(8), nullable=False),
        sa.Column('dev_id', sa.String(255)),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('status', sa.String(36), nullable=False),
        sa.Column('extra_info', sa.Text, nullable=True),
        sa.Column('instance_uuid', sa.String(36), nullable=True),
        sa.Column('request_id', sa.String(36), nullable=True),
        sa.Column('numa_node', sa.Integer, default=None),
        sa.Column('parent_addr', sa.String(12), nullable=True),
        sa.Column('uuid', sa.String(36)),
        sa.Index(
            'ix_pci_devices_instance_uuid_deleted',
            'instance_uuid', 'deleted'),
        sa.Index(
            'ix_pci_devices_compute_node_id_deleted',
            'compute_node_id', 'deleted'),
        sa.Index(
            'ix_pci_devices_compute_node_id_parent_addr_deleted',
            'compute_node_id', 'parent_addr', 'deleted'),
        UniqueConstraint(
            'compute_node_id', 'address', 'deleted',
            name='uniq_pci_devices0compute_node_id0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    provider_fw_rules = sa.Table('provider_fw_rules', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('protocol', sa.String(length=5)),
        sa.Column('from_port', sa.Integer),
        sa.Column('to_port', sa.Integer),
        sa.Column('cidr', Inet()),
        sa.Column('deleted', sa.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_classes = sa.Table('quota_classes', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('class_name', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255)),
        sa.Column('hard_limit', sa.Integer),
        sa.Column('deleted', sa.Integer),
        sa.Index('ix_quota_classes_class_name', 'class_name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_usages = sa.Table('quota_usages', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('in_use', sa.Integer, nullable=False),
        sa.Column('reserved', sa.Integer, nullable=False),
        sa.Column('until_refresh', sa.Integer),
        sa.Column('deleted', sa.Integer),
        sa.Column('user_id', sa.String(length=255)),
        sa.Index('ix_quota_usages_project_id', 'project_id'),
        sa.Index('ix_quota_usages_user_id_deleted', 'user_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quotas = sa.Table('quotas', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('hard_limit', sa.Integer),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'project_id', 'resource', 'deleted',
            name='uniq_quotas0project_id0resource0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    project_user_quotas = sa.Table('project_user_quotas', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Integer),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('hard_limit', sa.Integer, nullable=True),
        sa.Index(
            'project_user_quotas_project_id_deleted_idx',
            'project_id', 'deleted'),
        sa.Index(
            'project_user_quotas_user_id_deleted_idx',
            'user_id', 'deleted'),
        UniqueConstraint(
            'user_id', 'project_id', 'resource', 'deleted',
            name='uniq_project_user_quotas0user_id0project_id0resource0'
            'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    reservations = sa.Table('reservations', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column(
            'usage_id', sa.Integer,
            sa.ForeignKey('quota_usages.id', name='reservations_ibfk_1'),
            nullable=False),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255)),
        sa.Column('delta', sa.Integer, nullable=False),
        sa.Column('expire', sa.DateTime),
        sa.Column('deleted', sa.Integer),
        sa.Column('user_id', sa.String(length=255)),
        sa.Index('ix_reservations_project_id', 'project_id'),
        sa.Index('ix_reservations_user_id_deleted', 'user_id', 'deleted'),
        sa.Index('reservations_uuid_idx', 'uuid'),
        sa.Index('reservations_deleted_expire_idx', 'deleted', 'expire'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    resource_providers = sa.Table('resource_providers', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column('name', sa.Unicode(200), nullable=True),
        sa.Column('generation', sa.Integer, default=0),
        sa.Column('can_host', sa.Integer, default=0),
        UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        UniqueConstraint('name', name='uniq_resource_providers0name'),
        sa.Index('resource_providers_name_idx', 'name'),
        sa.Index('resource_providers_uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    resource_provider_aggregates = sa.Table(
        'resource_provider_aggregates', meta,
        sa.Column(
            'resource_provider_id', sa.Integer, primary_key=True,
            nullable=False),
        sa.Column(
            'aggregate_id', sa.Integer, primary_key=True, nullable=False),
        sa.Index(
            'resource_provider_aggregates_aggregate_id_idx', 'aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    s3_images = sa.Table('s3_images', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('deleted', sa.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_instance_association = sa.Table(
        'security_group_instance_association', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'security_group_id', sa.Integer,
            sa.ForeignKey(
                'security_groups.id',
                name='security_group_instance_association_ibfk_1'),
        ),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid',
                name='security_group_instance_association_instance_uuid_fkey'),
        ),
        sa.Column('deleted', sa.Integer),
        sa.Index(
            'security_group_instance_association_instance_uuid_idx',
            'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_rules = sa.Table('security_group_rules', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'parent_group_id', sa.Integer,
            sa.ForeignKey('security_groups.id')),
        sa.Column('protocol', sa.String(length=255)),
        sa.Column('from_port', sa.Integer),
        sa.Column('to_port', sa.Integer),
        sa.Column('cidr', Inet()),
        sa.Column('group_id', sa.Integer, sa.ForeignKey('security_groups.id')),
        sa.Column('deleted', sa.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_groups = sa.Table('security_groups', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(length=255)),
        sa.Column('description', sa.String(length=255)),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('deleted', sa.Integer),
        UniqueConstraint(
            'project_id', 'name', 'deleted',
            name='uniq_security_groups0project_id0name0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_default_rules = sa.Table(
        'security_group_default_rules', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('deleted', sa.Integer, default=0),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('protocol', sa.String(length=5)),
        sa.Column('from_port', sa.Integer),
        sa.Column('to_port', sa.Integer),
        sa.Column('cidr', Inet()),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    services = sa.Table('services', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(length=255)),
        sa.Column('binary', sa.String(length=255)),
        sa.Column('topic', sa.String(length=255)),
        sa.Column('report_count', sa.Integer, nullable=False),
        sa.Column('disabled', sa.Boolean),
        sa.Column('deleted', sa.Integer),
        sa.Column('disabled_reason', sa.String(length=255)),
        sa.Column('last_seen_up', sa.DateTime, nullable=True),
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column(
            'forced_down', sa.Boolean(create_constraint=False), default=False),
        sa.Column('version', sa.Integer, default=0),
        sa.Column('uuid', sa.String(36), nullable=True),
        sa.Index('services_uuid_idx', 'uuid', unique=True),
        UniqueConstraint(
            'host', 'topic', 'deleted',
            name='uniq_services0host0topic0deleted'),
        UniqueConstraint(
            'host', 'binary', 'deleted',
            name='uniq_services0host0binary0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshot_id_mappings = sa.Table('snapshot_id_mappings', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('deleted', sa.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshots = sa.Table('snapshots', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'id', sa.String(length=36), primary_key=True, nullable=False),
        sa.Column('volume_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('status', sa.String(length=255)),
        sa.Column('progress', sa.String(length=255)),
        sa.Column('volume_size', sa.Integer),
        sa.Column('scheduled_at', sa.DateTime),
        sa.Column('display_name', sa.String(length=255)),
        sa.Column('display_description', sa.String(length=255)),
        sa.Column('deleted', sa.String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tags = sa.Table('tags', meta,
        sa.Column(
            'resource_id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('tag', sa.Unicode(80), primary_key=True, nullable=False),
        sa.Index('tags_tag_idx', 'tag'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    task_log = sa.Table('task_log', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('task_name', sa.String(length=255), nullable=False),
        sa.Column('state', sa.String(length=255), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('period_beginning', sa.DateTime, nullable=False),
        sa.Column('period_ending', sa.DateTime, nullable=False),
        sa.Column('message', sa.String(length=255), nullable=False),
        sa.Column('task_items', sa.Integer),
        sa.Column('errors', sa.Integer),
        sa.Column('deleted', sa.Integer),
        sa.Index('ix_task_log_period_beginning', 'period_beginning'),
        sa.Index('ix_task_log_host', 'host'),
        sa.Index('ix_task_log_period_ending', 'period_ending'),
        UniqueConstraint(
            'task_name', 'host', 'period_beginning', 'period_ending',
            name='uniq_task_log0task_name0host0period_beginning0period_ending',
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    virtual_interfaces = sa.Table('virtual_interfaces', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('address', sa.String(length=255)),
        sa.Column('network_id', sa.Integer),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column(
            'instance_uuid', sa.String(length=36),
            sa.ForeignKey(
                'instances.uuid',
                name='virtual_interfaces_instance_uuid_fkey'),
            nullable=True),
        sa.Column('deleted', sa.Integer),
        sa.Column('tag', sa.String(255)),
        sa.Index('virtual_interfaces_instance_uuid_fkey', 'instance_uuid'),
        sa.Index('virtual_interfaces_network_id_idx', 'network_id'),
        sa.Index('virtual_interfaces_uuid_idx', 'uuid'),
        UniqueConstraint(
            'address', 'deleted',
            name='uniq_virtual_interfaces0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_id_mappings = sa.Table('volume_id_mappings', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('deleted', sa.Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_usage_cache = sa.Table('volume_usage_cache', meta,
        sa.Column('created_at', sa.DateTime(timezone=False)),
        sa.Column('updated_at', sa.DateTime(timezone=False)),
        sa.Column('deleted_at', sa.DateTime(timezone=False)),
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('volume_id', sa.String(36), nullable=False),
        sa.Column('tot_last_refreshed', sa.DateTime(timezone=False)),
        sa.Column('tot_reads', sa.BigInteger(), default=0),
        sa.Column('tot_read_bytes', sa.BigInteger(), default=0),
        sa.Column('tot_writes', sa.BigInteger(), default=0),
        sa.Column('tot_write_bytes', sa.BigInteger(), default=0),
        sa.Column('curr_last_refreshed', sa.DateTime(timezone=False)),
        sa.Column('curr_reads', sa.BigInteger(), default=0),
        sa.Column('curr_read_bytes', sa.BigInteger(), default=0),
        sa.Column('curr_writes', sa.BigInteger(), default=0),
        sa.Column('curr_write_bytes', sa.BigInteger(), default=0),
        sa.Column('deleted', sa.Integer),
        sa.Column('instance_uuid', sa.String(length=36)),
        sa.Column('project_id', sa.String(length=36)),
        sa.Column('user_id', sa.String(length=64)),
        sa.Column('availability_zone', sa.String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    # create all tables
    tables = [instances, aggregates, console_auth_tokens,
              console_pools, instance_types,
              security_groups, snapshots,
              # those that are children and others later
              agent_builds, aggregate_hosts, aggregate_metadata,
              block_device_mapping, bw_usage_cache, cells,
              certificates, compute_nodes, consoles,
              dns_domains, fixed_ips, floating_ips,
              instance_faults, instance_id_mappings, instance_info_caches,
              instance_metadata, instance_system_metadata,
              instance_type_extra_specs, instance_type_projects,
              instance_actions, instance_actions_events, instance_extra,
              groups, group_policy, group_member,
              key_pairs, migrations, networks,
              pci_devices, provider_fw_rules, quota_classes, quota_usages,
              quotas, project_user_quotas,
              reservations, s3_images, security_group_instance_association,
              security_group_rules, security_group_default_rules,
              services, snapshot_id_mappings, tags, task_log,
              virtual_interfaces,
              volume_id_mappings,
              volume_usage_cache,
              resource_providers, inventories, allocations,
              resource_provider_aggregates]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception('Exception while creating table.')
            raise

    # MySQL specific indexes
    if migrate_engine.name == 'mysql':
        # NOTE(stephenfin): For some reason, we have to put this within the if
        # statement to avoid it being evaluated for the sqlite case. Even
        # though we don't call create except in the MySQL case... Failure to do
        # this will result in the following ugly error message:
        #
        #   sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such
        #   index: instance_type_id
        #
        # Yeah, I don't get it either...
        mysql_specific_indexes = [
            sa.Index(
                'instance_type_id',
                instance_type_projects.c.instance_type_id),
            sa.Index('usage_id', reservations.c.usage_id),
            sa.Index(
                'security_group_id',
                security_group_instance_association.c.security_group_id),
        ]

        for index in mysql_specific_indexes:
            index.create(migrate_engine)

    if migrate_engine.name == 'mysql':
        # In Folsom we explicitly converted migrate_version to UTF8.
        migrate_engine.execute(
            'ALTER TABLE migrate_version CONVERT TO CHARACTER SET utf8')
        # Set default DB charset to UTF8.
        migrate_engine.execute(
            'ALTER DATABASE `%s` DEFAULT CHARACTER SET utf8' %
            migrate_engine.url.database)

        # NOTE(cdent): The resource_providers table is defined as latin1 to be
        # more efficient. Now we need the name column to be UTF8. We modify it
        # here otherwise the declarative handling in sqlalchemy gets confused.
        migrate_engine.execute(
            'ALTER TABLE resource_providers MODIFY name '
            'VARCHAR(200) CHARACTER SET utf8')

    _create_shadow_tables(migrate_engine)

    # TODO(stephenfin): Fix these various bugs in a follow-up

    # 298_mysql_extra_specs_binary_collation; we should update the shadow table
    # also

    if migrate_engine.name == 'mysql':
        # Use binary collation for extra specs table
        migrate_engine.execute(
            'ALTER TABLE instance_type_extra_specs '
            'CONVERT TO CHARACTER SET utf8 '
            'COLLATE utf8_bin'
        )
