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
from migrate import ForeignKeyConstraint
from oslo_log import log as logging
from sqlalchemy import Boolean, BigInteger, Column, DateTime, Enum, Float
from sqlalchemy import dialects
from sqlalchemy import ForeignKey, Index, Integer, MetaData, String, Table
from sqlalchemy import Text
from sqlalchemy.types import NullType
from sqlalchemy import Unicode

from nova.db.sqlalchemy import types
from nova.objects import keypair

LOG = logging.getLogger(__name__)


# Note on the autoincrement flag: this is defaulted for primary key columns
# of integral type, so is no longer set explicitly in such cases.

# NOTE(dprince): This wrapper allows us to easily match the Folsom MySQL
# Schema. In Folsom we created tables as latin1 and converted them to utf8
# later. This conversion causes some of the Text columns on MySQL to get
# created as mediumtext instead of just text.
def MediumText():
    return Text().with_variant(dialects.mysql.MEDIUMTEXT(), 'mysql')


def Inet():
    return String(length=43).with_variant(dialects.postgresql.INET(),
                  'postgresql')


def InetSmall():
    return String(length=39).with_variant(dialects.postgresql.INET(),
                  'postgresql')


def _create_shadow_tables(migrate_engine):
    meta = MetaData(migrate_engine)
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

        table = Table(table_name, meta, autoload=True)

        columns = []
        for column in table.columns:
            column_copy = None
            # NOTE(boris-42): BigInteger is not supported by sqlite, so
            #                 after copy it will have NullType, other
            #                 types that are used in Nova are supported by
            #                 sqlite.
            if isinstance(column.type, NullType):
                column_copy = Column(column.name, BigInteger(), default=0)

            if table_name == 'instances' and column.name == 'locked_by':
                enum = Enum(
                    'owner', 'admin', name='shadow_instances0locked_by',
                )
                column_copy = Column(column.name, enum)

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
                    column_copy = Column(
                        column.name, enum, nullable=False,
                        server_default=keypair.KEYPAIR_TYPE_SSH)
                elif (
                    table_name == 'migrations' and
                    column.name == 'migration_type'
                ):
                    enum = dialects.postgresql.ENUM(
                        'migration', 'resize', 'live-migration', 'evacuation',
                        name='migration_type', create_type=False)
                    column_copy = Column(column.name, enum, nullable=True)

            if column_copy is None:
                column_copy = column.copy()

            columns.append(column_copy)

        shadow_table = Table(
            'shadow_' + table_name, meta, *columns, mysql_engine='InnoDB',
        )

        try:
            shadow_table.create()
        except Exception:
            LOG.info(repr(shadow_table))
            LOG.exception('Exception while creating table.')
            raise


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    agent_builds = Table('agent_builds', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('hypervisor', String(length=255)),
        Column('os', String(length=255)),
        Column('architecture', String(length=255)),
        Column('version', String(length=255)),
        Column('url', String(length=255)),
        Column('md5hash', String(length=255)),
        Column('deleted', Integer),
        UniqueConstraint(
            'hypervisor', 'os', 'architecture', 'deleted',
            name='uniq_agent_builds0hypervisor0os0architecture0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_hosts = Table('aggregate_hosts', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column(
            'aggregate_id', Integer, ForeignKey('aggregates.id'),
            nullable=False),
        Column('deleted', Integer),
        UniqueConstraint(
            'host', 'aggregate_id', 'deleted',
            name='uniq_aggregate_hosts0host0aggregate_id0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_metadata = Table('aggregate_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column(
            'aggregate_id', Integer, ForeignKey('aggregates.id'),
            nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255), nullable=False),
        Column('deleted', Integer),
        UniqueConstraint(
            'aggregate_id', 'key', 'deleted',
            name='uniq_aggregate_metadata0aggregate_id0key0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregates = Table('aggregates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('deleted', Integer),
        Column('uuid', String(36)),
        Index('aggregate_uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    allocations = Table('allocations', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('resource_provider_id', Integer, nullable=False),
        Column('consumer_id', String(36), nullable=False),
        Column('resource_class_id', Integer, nullable=False),
        Column('used', Integer, nullable=False),
        Index(
            'allocations_resource_provider_class_used_idx',
            'resource_provider_id', 'resource_class_id', 'used'),
        Index('allocations_consumer_id_idx', 'consumer_id'),
        Index('allocations_resource_class_id_idx', 'resource_class_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    block_device_mapping = Table('block_device_mapping', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('device_name', String(length=255), nullable=True),
        Column('delete_on_termination', Boolean),
        Column('snapshot_id', String(length=36), nullable=True),
        Column('volume_id', String(length=36), nullable=True),
        Column('volume_size', Integer),
        Column('no_device', Boolean),
        Column('connection_info', MediumText()),
        Column('instance_uuid', String(length=36)),
        Column('deleted', Integer),
        Column('source_type', String(length=255), nullable=True),
        Column('destination_type', String(length=255), nullable=True),
        Column('guest_format', String(length=255), nullable=True),
        Column('device_type', String(length=255), nullable=True),
        Column('disk_bus', String(length=255), nullable=True),
        Column('boot_index', Integer),
        Column('image_id', String(length=36), nullable=True),
        Column('tag', String(255)),
        Column('attachment_id', String(36), nullable=True),
        Column('uuid', String(36), nullable=True),
        Column('volume_type', String(255), nullable=True),
        UniqueConstraint('uuid', name='uniq_block_device_mapping0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    bw_usage_cache = Table('bw_usage_cache', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('start_period', DateTime, nullable=False),
        Column('last_refreshed', DateTime),
        Column('bw_in', BigInteger),
        Column('bw_out', BigInteger),
        Column('mac', String(length=255)),
        Column('uuid', String(length=36)),
        Column('last_ctr_in', BigInteger()),
        Column('last_ctr_out', BigInteger()),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    cells = Table('cells', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('api_url', String(length=255)),
        Column('weight_offset', Float),
        Column('weight_scale', Float),
        Column('name', String(length=255)),
        Column('is_parent', Boolean),
        Column('deleted', Integer),
        Column('transport_url', String(length=255), nullable=False),
        UniqueConstraint(
            'name', 'deleted',
            name='uniq_cells0name0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    certificates = Table('certificates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('file_name', String(length=255)),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    compute_nodes = Table('compute_nodes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('service_id', Integer, nullable=True),
        Column('vcpus', Integer, nullable=False),
        Column('memory_mb', Integer, nullable=False),
        Column('local_gb', Integer, nullable=False),
        Column('vcpus_used', Integer, nullable=False),
        Column('memory_mb_used', Integer, nullable=False),
        Column('local_gb_used', Integer, nullable=False),
        Column('hypervisor_type', MediumText(), nullable=False),
        Column('hypervisor_version', Integer, nullable=False),
        Column('cpu_info', MediumText(), nullable=False),
        Column('disk_available_least', Integer),
        Column('free_ram_mb', Integer),
        Column('free_disk_gb', Integer),
        Column('current_workload', Integer),
        Column('running_vms', Integer),
        Column('hypervisor_hostname', String(length=255)),
        Column('deleted', Integer),
        Column('host_ip', InetSmall()),
        Column('supported_instances', Text),
        Column('pci_stats', Text, nullable=True),
        Column('metrics', Text, nullable=True),
        Column('extra_resources', Text, nullable=True),
        Column('stats', Text, default='{}'),
        Column('numa_topology', Text, nullable=True),
        Column('host', String(255), nullable=True),
        Column('ram_allocation_ratio', Float, nullable=True),
        Column('cpu_allocation_ratio', Float, nullable=True),
        Column('uuid', String(36), nullable=True),
        Column('disk_allocation_ratio', Float, nullable=True),
        Column('mapped', Integer, default=0, nullable=True),
        Index('compute_nodes_uuid_idx', 'uuid', unique=True),
        UniqueConstraint(
            'host', 'hypervisor_hostname', 'deleted',
            name='uniq_compute_nodes0host0hypervisor_hostname0deleted',
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    console_auth_tokens = Table('console_auth_tokens', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('token_hash', String(255), nullable=False),
        Column('console_type', String(255), nullable=False),
        Column('host', String(255), nullable=False),
        Column('port', Integer, nullable=False),
        Column('internal_access_path', String(255)),
        Column('instance_uuid', String(36), nullable=False),
        Column('expires', Integer, nullable=False),
        Column('access_url_base', String(255), nullable=True),
        Index('console_auth_tokens_instance_uuid_idx', 'instance_uuid'),
        Index('console_auth_tokens_host_expires_idx', 'host', 'expires'),
        Index('console_auth_tokens_token_hash_idx', 'token_hash'),
        Index(
            'console_auth_tokens_token_hash_instance_uuid_idx',
            'token_hash', 'instance_uuid'),
        UniqueConstraint(
            'token_hash', name='uniq_console_auth_tokens0token_hash'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    console_pools = Table('console_pools', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', InetSmall()),
        Column('username', String(length=255)),
        Column('password', String(length=255)),
        Column('console_type', String(length=255)),
        Column('public_hostname', String(length=255)),
        Column('host', String(length=255)),
        Column('compute_host', String(length=255)),
        Column('deleted', Integer),
        UniqueConstraint(
            'host', 'console_type', 'compute_host', 'deleted',
            name='uniq_console_pools0host0console_type0compute_host0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    consoles = Table('consoles', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_name', String(length=255)),
        Column('password', String(length=255)),
        Column('port', Integer),
        Column('pool_id', Integer, ForeignKey('console_pools.id')),
        Column(
            'instance_uuid', String(length=36),
            ForeignKey('instances.uuid', name='consoles_instance_uuid_fkey')),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    dns_domains = Table('dns_domains', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('domain', String(length=255), primary_key=True, nullable=False),
        Column('scope', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('project_id', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    fixed_ips = Table('fixed_ips', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', InetSmall()),
        Column('network_id', Integer),
        Column('allocated', Boolean),
        Column('leased', Boolean),
        Column('reserved', Boolean),
        Column('virtual_interface_id', Integer),
        Column('host', String(length=255)),
        Column('instance_uuid', String(length=36)),
        Column('deleted', Integer),
        UniqueConstraint(
            'address', 'deleted',
            name='uniq_fixed_ips0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    floating_ips = Table('floating_ips', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', InetSmall()),
        Column('fixed_ip_id', Integer),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('auto_assigned', Boolean),
        Column('pool', String(length=255)),
        Column('interface', String(length=255)),
        Column('deleted', Integer),
        UniqueConstraint(
            'address', 'deleted',
            name='uniq_floating_ips0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_faults = Table('instance_faults', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=36)),
        Column('code', Integer, nullable=False),
        Column('message', String(length=255)),
        Column('details', MediumText()),
        Column('host', String(length=255)),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_id_mappings = Table('instance_id_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(36), nullable=False),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_info_caches = Table('instance_info_caches', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('network_info', MediumText()),
        Column('instance_uuid', String(length=36), nullable=False),
        Column('deleted', Integer),
        UniqueConstraint(
            'instance_uuid',
            name='uniq_instance_info_caches0instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    groups = Table('instance_groups', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('uuid', String(length=36), nullable=False),
        Column('name', String(length=255)),
        UniqueConstraint('uuid', 'deleted',
                         name='uniq_instance_groups0uuid0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_policy = Table('instance_group_policy', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('policy', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_member = Table('instance_group_member', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_id', String(length=255)),
        Column('group_id', Integer, ForeignKey('instance_groups.id'),
               nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_metadata = Table('instance_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        Column('instance_uuid', String(length=36), nullable=True),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_system_metadata = Table('instance_system_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=36), nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255)),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_type_extra_specs = Table('instance_type_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_type_id', Integer, ForeignKey('instance_types.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        Column('deleted', Integer),
        UniqueConstraint(
            'instance_type_id', 'key', 'deleted',
            name='uniq_instance_type_extra_specs0instance_type_id0key0deleted'
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_type_projects = Table('instance_type_projects', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_type_id', Integer, nullable=False),
        Column('project_id', String(length=255)),
        Column('deleted', Integer),
        UniqueConstraint(
            'instance_type_id', 'project_id', 'deleted',
            name='uniq_instance_type_projects0instance_type_id0project_id'
            '0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_types = Table('instance_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('name', String(length=255)),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('memory_mb', Integer, nullable=False),
        Column('vcpus', Integer, nullable=False),
        Column('swap', Integer, nullable=False),
        Column('vcpu_weight', Integer),
        Column('flavorid', String(length=255)),
        Column('rxtx_factor', Float),
        Column('root_gb', Integer),
        Column('ephemeral_gb', Integer),
        Column('disabled', Boolean),
        Column('is_public', Boolean),
        Column('deleted', Integer),
        UniqueConstraint(
            'name', 'deleted',
            name='uniq_instance_types0name0deleted'),
        UniqueConstraint(
            'flavorid', 'deleted',
            name='uniq_instance_types0flavorid0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instances = Table('instances', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('internal_id', Integer),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('image_ref', String(length=255)),
        Column('kernel_id', String(length=255)),
        Column('ramdisk_id', String(length=255)),
        Column('launch_index', Integer),
        Column('key_name', String(length=255)),
        Column('key_data', MediumText()),
        Column('power_state', Integer),
        Column('vm_state', String(length=255)),
        Column('memory_mb', Integer),
        Column('vcpus', Integer),
        Column('hostname', String(length=255)),
        Column('host', String(length=255)),
        Column('user_data', MediumText()),
        Column('reservation_id', String(length=255)),
        Column('launched_at', DateTime),
        Column('terminated_at', DateTime),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('locked', Boolean),
        Column('os_type', String(length=255)),
        Column('launched_on', MediumText()),
        Column('instance_type_id', Integer),
        Column('vm_mode', String(length=255)),
        Column('uuid', String(length=36), nullable=False),
        Column('architecture', String(length=255)),
        Column('root_device_name', String(length=255)),
        Column('access_ip_v4', InetSmall()),
        Column('access_ip_v6', InetSmall()),
        Column('config_drive', String(length=255)),
        Column('task_state', String(length=255)),
        Column('default_ephemeral_device', String(length=255)),
        Column('default_swap_device', String(length=255)),
        Column('progress', Integer),
        Column('auto_disk_config', Boolean),
        Column('shutdown_terminate', Boolean),
        Column('disable_terminate', Boolean),
        Column('root_gb', Integer),
        Column('ephemeral_gb', Integer),
        Column('cell_name', String(length=255)),
        Column('node', String(length=255)),
        Column('deleted', Integer),
        Column(
            'locked_by', Enum('owner', 'admin', name='instances0locked_by')),
        Column('cleaned', Integer, default=0),
        Column('ephemeral_key_uuid', String(36)),
        # NOTE(danms): This column originally included default=False. We
        # discovered in bug #1862205 that this will attempt to rewrite
        # the entire instances table with that value, which can time out
        # for large data sets (and does not even abort).
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        Column('hidden', Boolean(create_constraint=False)),
        Index('uuid', 'uuid', unique=True),
        UniqueConstraint('uuid', name='uniq_instances0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_actions = Table('instance_actions', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('action', String(length=255)),
        Column('instance_uuid', String(length=36)),
        Column('request_id', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('start_time', DateTime),
        Column('finish_time', DateTime),
        Column('message', String(length=255)),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_actions_events = Table('instance_actions_events', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('event', String(length=255)),
        Column('action_id', Integer, ForeignKey('instance_actions.id')),
        Column('start_time', DateTime),
        Column('finish_time', DateTime),
        Column('result', String(length=255)),
        Column('traceback', Text),
        Column('deleted', Integer),
        Column('host', String(255)),
        Column('details', Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_extra = Table('instance_extra', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=36), nullable=False),
        Column('numa_topology', Text, nullable=True),
        Column('pci_requests', Text, nullable=True),
        Column('flavor', Text, nullable=True),
        Column('vcpu_model', Text, nullable=True),
        Column('migration_context', Text, nullable=True),
        Column('keypairs', Text, nullable=True),
        Column('device_metadata', Text, nullable=True),
        Column('trusted_certs', Text, nullable=True),
        Column('vpmems', Text, nullable=True),
        Column('resources', Text, nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    inventories = Table('inventories', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('resource_provider_id', Integer, nullable=False),
        Column('resource_class_id', Integer, nullable=False),
        Column('total', Integer, nullable=False),
        Column('reserved', Integer, nullable=False),
        Column('min_unit', Integer, nullable=False),
        Column('max_unit', Integer, nullable=False),
        Column('step_size', Integer, nullable=False),
        Column('allocation_ratio', Float, nullable=False),
        Index(
            'inventories_resource_provider_id_idx', 'resource_provider_id'),
        Index(
            'inventories_resource_class_id_idx', 'resource_class_id'),
        Index(
            'inventories_resource_provider_resource_class_idx',
            'resource_provider_id', 'resource_class_id'),
        UniqueConstraint(
            'resource_provider_id', 'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    key_pairs = Table('key_pairs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('user_id', String(length=255)),
        Column('fingerprint', String(length=255)),
        Column('public_key', MediumText()),
        Column('deleted', Integer),
        Column(
            'type', Enum('ssh', 'x509', name='keypair_types'), nullable=False,
            server_default=keypair.KEYPAIR_TYPE_SSH),
        UniqueConstraint(
            'user_id', 'name', 'deleted',
            name='uniq_key_pairs0user_id0name0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    migrations = Table('migrations', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('source_compute', String(length=255)),
        Column('dest_compute', String(length=255)),
        Column('dest_host', String(length=255)),
        Column('status', String(length=255)),
        Column('instance_uuid', String(length=36)),
        Column('old_instance_type_id', Integer),
        Column('new_instance_type_id', Integer),
        Column('source_node', String(length=255)),
        Column('dest_node', String(length=255)),
        Column('deleted', Integer),
        Column(
            'migration_type',
            Enum(
                'migration', 'resize', 'live-migration', 'evacuation',
                name='migration_type'),
            nullable=True),
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        Column('hidden', Boolean(create_constraint=False), default=False),
        Column('memory_total', BigInteger, nullable=True),
        Column('memory_processed', BigInteger, nullable=True),
        Column('memory_remaining', BigInteger, nullable=True),
        Column('disk_total', BigInteger, nullable=True),
        Column('disk_processed', BigInteger, nullable=True),
        Column('disk_remaining', BigInteger, nullable=True),
        Column('uuid', String(36)),
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        Column(
            'cross_cell_move', Boolean(create_constraint=False),
            default=False),
        Column('user_id', String(255), nullable=True),
        Column('project_id', String(255), nullable=True),
        Index('migrations_uuid', 'uuid', unique=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    networks = Table('networks', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('injected', Boolean),
        Column('cidr', Inet()),
        Column('netmask', InetSmall()),
        Column('bridge', String(length=255)),
        Column('gateway', InetSmall()),
        Column('broadcast', InetSmall()),
        Column('dns1', InetSmall()),
        Column('vlan', Integer),
        Column('vpn_public_address', InetSmall()),
        Column('vpn_public_port', Integer),
        Column('vpn_private_address', InetSmall()),
        Column('dhcp_start', InetSmall()),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('cidr_v6', Inet()),
        Column('gateway_v6', InetSmall()),
        Column('label', String(length=255)),
        Column('netmask_v6', InetSmall()),
        Column('bridge_interface', String(length=255)),
        Column('multi_host', Boolean),
        Column('dns2', InetSmall()),
        Column('uuid', String(length=36)),
        Column('priority', Integer),
        Column('rxtx_base', Integer),
        Column('deleted', Integer),
        Column('mtu', Integer),
        Column('dhcp_server', types.IPAddress),
        # NOTE(stephenfin): These were originally added by sqlalchemy-migrate
        # which did not generate the constraints
        Column('enable_dhcp', Boolean(create_constraint=False), default=True),
        Column(
            'share_address', Boolean(create_constraint=False), default=False),
        UniqueConstraint('vlan', 'deleted', name='uniq_networks0vlan0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    pci_devices = Table('pci_devices', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Integer, default=0, nullable=False),
        Column('id', Integer, primary_key=True),
        Column('compute_node_id', Integer, nullable=False),
        Column('address', String(12), nullable=False),
        Column('product_id', String(4)),
        Column('vendor_id', String(4)),
        Column('dev_type', String(8)),
        Column('dev_id', String(255)),
        Column('label', String(255), nullable=False),
        Column('status', String(36), nullable=False),
        Column('extra_info', Text, nullable=True),
        Column('instance_uuid', String(36), nullable=True),
        Column('request_id', String(36), nullable=True),
        Column('numa_node', Integer, default=None),
        Column('parent_addr', String(12), nullable=True),
        Column('uuid', String(36)),
        Index('ix_pci_devices_instance_uuid_deleted',
              'instance_uuid', 'deleted'),
        Index('ix_pci_devices_compute_node_id_deleted',
              'compute_node_id', 'deleted'),
        UniqueConstraint(
            'compute_node_id', 'address', 'deleted',
            name='uniq_pci_devices0compute_node_id0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8')

    provider_fw_rules = Table('provider_fw_rules', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('protocol', String(length=5)),
        Column('from_port', Integer),
        Column('to_port', Integer),
        Column('cidr', Inet()),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_classes = Table('quota_classes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('class_name', String(length=255)),
        Column('resource', String(length=255)),
        Column('hard_limit', Integer),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_usages = Table('quota_usages', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255)),
        Column('in_use', Integer, nullable=False),
        Column('reserved', Integer, nullable=False),
        Column('until_refresh', Integer),
        Column('deleted', Integer),
        Column('user_id', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quotas = Table('quotas', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255), nullable=False),
        Column('hard_limit', Integer),
        Column('deleted', Integer),
        UniqueConstraint(
            'project_id', 'resource', 'deleted',
            name='uniq_quotas0project_id0resource0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    project_user_quotas = Table('project_user_quotas', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer),
        Column('user_id', String(length=255), nullable=False),
        Column('project_id', String(length=255), nullable=False),
        Column('resource', String(length=255), nullable=False),
        Column('hard_limit', Integer, nullable=True),
        UniqueConstraint(
            'user_id', 'project_id', 'resource', 'deleted',
            name='uniq_project_user_quotas0user_id0project_id0resource0'
            'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    reservations = Table('reservations', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('usage_id', Integer, nullable=False),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255)),
        Column('delta', Integer, nullable=False),
        Column('expire', DateTime),
        Column('deleted', Integer),
        Column('user_id', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    resource_providers = Table('resource_providers', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(36), nullable=False),
        Column('name', Unicode(200), nullable=True),
        Column('generation', Integer, default=0),
        Column('can_host', Integer, default=0),
        UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        UniqueConstraint('name', name='uniq_resource_providers0name'),
        Index('resource_providers_name_idx', 'name'),
        Index('resource_providers_uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    resource_provider_aggregates = Table('resource_provider_aggregates', meta,
        Column(
            'resource_provider_id', Integer, primary_key=True, nullable=False),
        Column('aggregate_id', Integer, primary_key=True, nullable=False),
        Index('resource_provider_aggregates_aggregate_id_idx', 'aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    s3_images = Table('s3_images', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_instance_association = \
        Table('security_group_instance_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('security_group_id', Integer),
        Column('instance_uuid', String(length=36)),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_rules = Table('security_group_rules', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('parent_group_id', Integer, ForeignKey('security_groups.id')),
        Column('protocol', String(length=255)),
        Column('from_port', Integer),
        Column('to_port', Integer),
        Column('cidr', Inet()),
        Column('group_id', Integer, ForeignKey('security_groups.id')),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_groups = Table('security_groups', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('description', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('deleted', Integer),
        UniqueConstraint(
            'project_id', 'name', 'deleted',
            name='uniq_security_groups0project_id0name0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_default_rules = Table('security_group_default_rules', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer, default=0),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('protocol', String(length=5)),
        Column('from_port', Integer),
        Column('to_port', Integer),
        Column('cidr', Inet()),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    services = Table('services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('binary', String(length=255)),
        Column('topic', String(length=255)),
        Column('report_count', Integer, nullable=False),
        Column('disabled', Boolean),
        Column('deleted', Integer),
        Column('disabled_reason', String(length=255)),
        Column('last_seen_up', DateTime, nullable=True),
        # NOTE(stephenfin): This was originally added by sqlalchemy-migrate
        # which did not generate the constraints
        Column('forced_down', Boolean(create_constraint=False), default=False),
        Column('version', Integer, default=0),
        Column('uuid', String(36), nullable=True),
        Index('services_uuid_idx', 'uuid', unique=True),
        UniqueConstraint(
            'host', 'topic', 'deleted',
            name='uniq_services0host0topic0deleted'),
        UniqueConstraint(
            'host', 'binary', 'deleted',
            name='uniq_services0host0binary0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshot_id_mappings = Table('snapshot_id_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshots = Table('snapshots', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', String(length=36), primary_key=True, nullable=False),
        Column('volume_id', String(length=36), nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('status', String(length=255)),
        Column('progress', String(length=255)),
        Column('volume_size', Integer),
        Column('scheduled_at', DateTime),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('deleted', String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tags = Table('tags', meta,
        Column('resource_id', String(36), primary_key=True, nullable=False),
        Column('tag', Unicode(80), primary_key=True, nullable=False),
        Index('tags_tag_idx', 'tag'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    task_log = Table('task_log', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('task_name', String(length=255), nullable=False),
        Column('state', String(length=255), nullable=False),
        Column('host', String(length=255), nullable=False),
        Column('period_beginning', DateTime, nullable=False),
        Column('period_ending', DateTime, nullable=False),
        Column('message', String(length=255), nullable=False),
        Column('task_items', Integer),
        Column('errors', Integer),
        Column('deleted', Integer),
        UniqueConstraint(
            'task_name', 'host', 'period_beginning', 'period_ending',
            name='uniq_task_log0task_name0host0period_beginning0period_ending',
        ),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    virtual_interfaces = Table('virtual_interfaces', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255)),
        Column('network_id', Integer),
        Column('uuid', String(length=36)),
        Column('instance_uuid', String(length=36), nullable=True),
        Column('deleted', Integer),
        Column('tag', String(255)),
        UniqueConstraint(
            'address', 'deleted',
            name='uniq_virtual_interfaces0address0deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_id_mappings = Table('volume_id_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('deleted', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_usage_cache = Table('volume_usage_cache', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('volume_id', String(36), nullable=False),
        Column('tot_last_refreshed', DateTime(timezone=False)),
        Column('tot_reads', BigInteger(), default=0),
        Column('tot_read_bytes', BigInteger(), default=0),
        Column('tot_writes', BigInteger(), default=0),
        Column('tot_write_bytes', BigInteger(), default=0),
        Column('curr_last_refreshed', DateTime(timezone=False)),
        Column('curr_reads', BigInteger(), default=0),
        Column('curr_read_bytes', BigInteger(), default=0),
        Column('curr_writes', BigInteger(), default=0),
        Column('curr_write_bytes', BigInteger(), default=0),
        Column('deleted', Integer),
        Column('instance_uuid', String(length=36)),
        Column('project_id', String(length=36)),
        Column('user_id', String(length=36)),
        Column('availability_zone', String(length=255)),
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

    # Common indexes (indexes we apply to all databases)
    # NOTE: order specific for MySQL diff support
    common_indexes = [

        # aggregate_metadata
        Index('aggregate_metadata_key_idx', aggregate_metadata.c.key),
        Index('aggregate_metadata_value_idx', aggregate_metadata.c.value),

        # agent_builds
        Index('agent_builds_hypervisor_os_arch_idx',
              agent_builds.c.hypervisor,
              agent_builds.c.os,
              agent_builds.c.architecture),

        # block_device_mapping
        Index('snapshot_id', block_device_mapping.c.snapshot_id),
        Index('volume_id', block_device_mapping.c.volume_id),
        Index('block_device_mapping_instance_uuid_idx',
              block_device_mapping.c.instance_uuid),
        Index('block_device_mapping_instance_uuid_device_name_idx',
              block_device_mapping.c.instance_uuid,
              block_device_mapping.c.device_name),
        Index('block_device_mapping_instance_uuid_volume_id_idx',
              block_device_mapping.c.instance_uuid,
              block_device_mapping.c.volume_id),

        # bw_usage_cache
        Index('bw_usage_cache_uuid_start_period_idx',
              bw_usage_cache.c.uuid, bw_usage_cache.c.start_period),

        # certificates
        Index('certificates_project_id_deleted_idx',
              certificates.c.project_id, certificates.c.deleted),
        Index('certificates_user_id_deleted_idx', certificates.c.user_id,
              certificates.c.deleted),

        # consoles
        Index('consoles_instance_uuid_idx', consoles.c.instance_uuid),

        # dns_domains
        Index('dns_domains_domain_deleted_idx',
              dns_domains.c.domain, dns_domains.c.deleted),
        Index('dns_domains_project_id_idx', dns_domains.c.project_id),

        # fixed_ips
        Index('network_id', fixed_ips.c.network_id),
        Index('address', fixed_ips.c.address),
        Index('fixed_ips_instance_uuid_fkey', fixed_ips.c.instance_uuid),
        Index('fixed_ips_virtual_interface_id_fkey',
              fixed_ips.c.virtual_interface_id),
        Index('fixed_ips_host_idx', fixed_ips.c.host),
        Index('fixed_ips_network_id_host_deleted_idx', fixed_ips.c.network_id,
              fixed_ips.c.host, fixed_ips.c.deleted),
        Index('fixed_ips_address_reserved_network_id_deleted_idx',
              fixed_ips.c.address, fixed_ips.c.reserved,
              fixed_ips.c.network_id, fixed_ips.c.deleted),
        Index('fixed_ips_deleted_allocated_idx', fixed_ips.c.address,
              fixed_ips.c.deleted, fixed_ips.c.allocated),
        Index('fixed_ips_deleted_allocated_updated_at_idx',
              fixed_ips.c.deleted, fixed_ips.c.allocated,
              fixed_ips.c.updated_at),

        # floating_ips
        Index('fixed_ip_id', floating_ips.c.fixed_ip_id),
        Index('floating_ips_host_idx', floating_ips.c.host),
        Index('floating_ips_project_id_idx', floating_ips.c.project_id),
        Index('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
              floating_ips.c.pool, floating_ips.c.deleted,
              floating_ips.c.fixed_ip_id, floating_ips.c.project_id),

        # group_member
        Index('instance_group_member_instance_idx',
              group_member.c.instance_id),

        # group_policy
        Index('instance_group_policy_policy_idx', group_policy.c.policy),

        # instances
        Index('instances_reservation_id_idx',
              instances.c.reservation_id),
        Index('instances_terminated_at_launched_at_idx',
              instances.c.terminated_at,
              instances.c.launched_at),
        Index('instances_task_state_updated_at_idx',
              instances.c.task_state,
              instances.c.updated_at),
        Index('instances_uuid_deleted_idx', instances.c.uuid,
              instances.c.deleted),
        Index('instances_host_node_deleted_idx', instances.c.host,
              instances.c.node, instances.c.deleted),
        Index('instances_host_deleted_cleaned_idx',
              instances.c.host, instances.c.deleted,
              instances.c.cleaned),
        Index('instances_project_id_deleted_idx',
              instances.c.project_id, instances.c.deleted),
        Index('instances_deleted_created_at_idx',
              instances.c.deleted, instances.c.created_at),
        Index('instances_project_id_idx', instances.c.project_id),
        Index('instances_updated_at_project_id_idx',
              instances.c.updated_at, instances.c.project_id),

        # instance_actions
        Index('instance_uuid_idx', instance_actions.c.instance_uuid),
        Index('request_id_idx', instance_actions.c.request_id),
        Index(
            'instance_actions_instance_uuid_updated_at_idx',
            instance_actions.c.instance_uuid, instance_actions.c.updated_at),

        # instance_extra
        Index('instance_extra_idx', instance_extra.c.instance_uuid),

        # instance_faults
        Index('instance_faults_host_idx', instance_faults.c.host),
        Index('instance_faults_instance_uuid_deleted_created_at_idx',
              instance_faults.c.instance_uuid, instance_faults.c.deleted,
              instance_faults.c.created_at),

        # instance_id_mappings
        Index('ix_instance_id_mappings_uuid', instance_id_mappings.c.uuid),

        # instance_metadata
        Index('instance_metadata_instance_uuid_idx',
              instance_metadata.c.instance_uuid),

        # instance_system_metadata
        Index('instance_uuid', instance_system_metadata.c.instance_uuid),

        # instance_type_extra_specs
        Index('instance_type_extra_specs_instance_type_id_key_idx',
              instance_type_extra_specs.c.instance_type_id,
              instance_type_extra_specs.c.key),

        # migrations
        Index('migrations_by_host_nodes_and_status_idx',
              migrations.c.deleted, migrations.c.source_compute,
              migrations.c.dest_compute, migrations.c.source_node,
              migrations.c.dest_node, migrations.c.status),
        Index('migrations_instance_uuid_and_status_idx',
              migrations.c.deleted, migrations.c.instance_uuid,
              migrations.c.status),
        Index('migrations_updated_at_idx', migrations.c.updated_at),

        # networks
        Index('networks_host_idx', networks.c.host),
        Index('networks_cidr_v6_idx', networks.c.cidr_v6),
        Index('networks_bridge_deleted_idx', networks.c.bridge,
              networks.c.deleted),
        Index('networks_project_id_deleted_idx', networks.c.project_id,
              networks.c.deleted),
        Index('networks_uuid_project_id_deleted_idx',
              networks.c.uuid, networks.c.project_id, networks.c.deleted),
        Index('networks_vlan_deleted_idx', networks.c.vlan,
              networks.c.deleted),

        # pci_devices
        Index('ix_pci_devices_compute_node_id_parent_addr_deleted',
              pci_devices.c.compute_node_id,
              pci_devices.c.parent_addr,
              pci_devices.c.deleted),

        # project_user_quotas
        Index('project_user_quotas_project_id_deleted_idx',
              project_user_quotas.c.project_id,
              project_user_quotas.c.deleted),
        Index('project_user_quotas_user_id_deleted_idx',
              project_user_quotas.c.user_id, project_user_quotas.c.deleted),

        # reservations
        Index('ix_reservations_project_id', reservations.c.project_id),
        Index('ix_reservations_user_id_deleted',
              reservations.c.user_id, reservations.c.deleted),
        Index('reservations_uuid_idx', reservations.c.uuid),
        Index('reservations_deleted_expire_idx',
              reservations.c.deleted, reservations.c.expire),

        # security_group_instance_association
        Index('security_group_instance_association_instance_uuid_idx',
              security_group_instance_association.c.instance_uuid),

        # task_log
        Index('ix_task_log_period_beginning', task_log.c.period_beginning),
        Index('ix_task_log_host', task_log.c.host),
        Index('ix_task_log_period_ending', task_log.c.period_ending),

        # quota_classes
        Index('ix_quota_classes_class_name', quota_classes.c.class_name),

        # quota_usages
        Index('ix_quota_usages_project_id', quota_usages.c.project_id),
        Index('ix_quota_usages_user_id_deleted',
              quota_usages.c.user_id, quota_usages.c.deleted),

        # virtual_interfaces
        Index('virtual_interfaces_instance_uuid_fkey',
              virtual_interfaces.c.instance_uuid),
        Index('virtual_interfaces_network_id_idx',
              virtual_interfaces.c.network_id),
        Index('virtual_interfaces_uuid_idx',
              virtual_interfaces.c.uuid),
    ]

    # MySQL specific indexes
    if migrate_engine.name == 'mysql':
        # created first (to preserve ordering for schema diffs)
        # NOTE(stephenfin): For some reason, we have to put this within the if
        # statement to avoid it being evaluated for the sqlite case. Even
        # though we don't call create except in the MySQL case... Failure to do
        # this will result in the following ugly error message:
        #
        #   sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such
        #   index: instance_type_id
        #
        # Yeah, I don't get it either...
        mysql_pre_indexes = [
            Index(
                'instance_type_id', instance_type_projects.c.instance_type_id),
            Index('usage_id', reservations.c.usage_id),
            Index(
                'security_group_id',
                security_group_instance_association.c.security_group_id),
        ]

        for index in mysql_pre_indexes:
            index.create(migrate_engine)

        # mysql-specific index by leftmost 100 chars.  (mysql gets angry if the
        # index key length is too long.)
        sql = ("create index migrations_by_host_nodes_and_status_idx ON "
               "migrations (deleted, source_compute(100), dest_compute(100), "
               "source_node(100), dest_node(100), status)")
        migrate_engine.execute(sql)

    POSTGRES_INDEX_SKIPS = []

    MYSQL_INDEX_SKIPS = [
        # we create this one manually for MySQL above
        'migrations_by_host_nodes_and_status_idx'
    ]

    for index in common_indexes:
        if ((migrate_engine.name == 'postgresql' and
                index.name in POSTGRES_INDEX_SKIPS) or
            (migrate_engine.name == 'mysql' and
                index.name in MYSQL_INDEX_SKIPS)):
            continue
        else:
            index.create(migrate_engine)

    # Common foreign keys
    fkeys = [
        [
            [instance_type_projects.c.instance_type_id],
            [instance_types.c.id],
            'instance_type_projects_ibfk_1',
        ],
        [
            [reservations.c.usage_id],
            [quota_usages.c.id],
            'reservations_ibfk_1',
        ],
        [
            [security_group_instance_association.c.security_group_id],
            [security_groups.c.id],
            'security_group_instance_association_ibfk_1',
        ],
        [
            [fixed_ips.c.instance_uuid],
            [instances.c.uuid],
            'fixed_ips_instance_uuid_fkey',
        ],
        [
            [block_device_mapping.c.instance_uuid],
            [instances.c.uuid],
            'block_device_mapping_instance_uuid_fkey',
        ],
        [
            [instance_info_caches.c.instance_uuid],
            [instances.c.uuid],
            'instance_info_caches_instance_uuid_fkey',
        ],
        [
            [instance_metadata.c.instance_uuid],
            [instances.c.uuid],
            'instance_metadata_instance_uuid_fkey',
        ],
        [
            [instance_system_metadata.c.instance_uuid],
            [instances.c.uuid],
            'instance_system_metadata_ibfk_1',
        ],
        [
            [security_group_instance_association.c.instance_uuid],
            [instances.c.uuid],
            'security_group_instance_association_instance_uuid_fkey',
        ],
        [
            [virtual_interfaces.c.instance_uuid],
            [instances.c.uuid],
            'virtual_interfaces_instance_uuid_fkey',
        ],
        [
            [instance_actions.c.instance_uuid],
            [instances.c.uuid],
            'fk_instance_actions_instance_uuid',
        ],
        [
            [instance_faults.c.instance_uuid],
            [instances.c.uuid],
            'fk_instance_faults_instance_uuid',
        ],
        [
            [migrations.c.instance_uuid],
            [instances.c.uuid],
            'fk_migrations_instance_uuid',
        ],
    ]

    for fkey_pair in fkeys:
        if migrate_engine.name in ('mysql', 'sqlite'):
            # For MySQL we name our fkeys explicitly
            # so they match Havana
            fkey = ForeignKeyConstraint(
                columns=fkey_pair[0], refcolumns=fkey_pair[1],
                name=fkey_pair[2])
            fkey.create()
        elif migrate_engine.name == 'postgresql':
            # PostgreSQL names things like it wants (correct and compatible!)
            fkey = ForeignKeyConstraint(
                columns=fkey_pair[0], refcolumns=fkey_pair[1])
            fkey.create()

    # TODO(stephenfin): Fold these in somehow
    fkey = ForeignKeyConstraint(
        columns=[pci_devices.c.compute_node_id],
        refcolumns=[compute_nodes.c.id])
    fkey.create()

    fkey = ForeignKeyConstraint(
        columns=[instance_extra.c.instance_uuid],
        refcolumns=[instances.c.uuid])
    fkey.create()

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

    # 244_increase_user_id_length_volume_usage_cache; this alternation should
    # apply to shadow tables also

    table = Table('volume_usage_cache', meta, autoload=True)
    table.c.user_id.alter(type=String(64))

    # 247_nullable_mismatch; these alterations should apply to shadow tables
    # also

    table = Table('quota_usages', meta, autoload=True)
    table.c.resource.alter(nullable=False)

    table = Table('pci_devices', meta, autoload=True)
    table.c.deleted.alter(nullable=True)
    table.c.product_id.alter(nullable=False)
    table.c.vendor_id.alter(nullable=False)
    table.c.dev_type.alter(nullable=False)

    # 252_add_instance_extra_table; we don't create indexes for shadow tables
    # in general and these should be removed

    table = Table('shadow_instance_extra', meta, autoload=True)
    idx = Index('shadow_instance_extra_idx', table.c.instance_uuid)
    idx.create(migrate_engine)

    # 280_add_nullable_false_to_keypairs_name; this should apply to the shadow
    # table also

    # Note: Since we are altering name field, this constraint on name needs to
    # first be dropped before we can alter name. We then re-create the same
    # constraint.
    UniqueConstraint(
        'user_id', 'name', 'deleted', table=key_pairs,
        name='uniq_key_pairs0user_id0name0deleted'
    ).drop()
    key_pairs.c.name.alter(nullable=False)
    UniqueConstraint(
        'user_id', 'name', 'deleted', table=key_pairs,
        name='uniq_key_pairs0user_id0name0deleted',
    ).create()

    # 298_mysql_extra_specs_binary_collation; we should update the shadow table
    # also

    if migrate_engine.name == 'mysql':
        # Use binary collation for extra specs table
        migrate_engine.execute(
            'ALTER TABLE instance_type_extra_specs '
            'CONVERT TO CHARACTER SET utf8 '
            'COLLATE utf8_bin'
        )

    # 373_migration_uuid; we should't create indexes for shadow tables

    table = Table('shadow_migrations', meta, autoload=True)
    idx = Index('shadow_migrations_uuid', table.c.uuid, unique=True)
    idx.create(migrate_engine)
