# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from sqlalchemy import Boolean, BigInteger, Column, DateTime, Float, ForeignKey
from sqlalchemy import Index, Integer, MetaData, String, Table, Text
from sqlalchemy import dialects

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


# Note on the autoincrement flag: this is defaulted for primary key columns
# of integral type, so is no longer set explicitly in such cases.

# NOTE(dprince): This wrapper allows us to easily match the Folsom MySQL
# Schema. In Folsom we created tables as latin1 and converted them to utf8
# later. This conversion causes some of the Text columns on MySQL to get
# created as mediumtext instead of just text.
def MediumText():
    return Text().with_variant(dialects.mysql.MEDIUMTEXT(), 'mysql')


def _populate_instance_types(instance_types_table):
    default_inst_types = {
        'm1.tiny': dict(mem=512, vcpus=1, root_gb=1, eph_gb=0, flavid=1),
        'm1.small': dict(mem=2048, vcpus=1, root_gb=20, eph_gb=0, flavid=2),
        'm1.medium': dict(mem=4096, vcpus=2, root_gb=40, eph_gb=0, flavid=3),
        'm1.large': dict(mem=8192, vcpus=4, root_gb=80, eph_gb=0, flavid=4),
        'm1.xlarge': dict(mem=16384, vcpus=8, root_gb=160, eph_gb=0, flavid=5)
        }

    try:
        i = instance_types_table.insert()
        for name, values in default_inst_types.iteritems():
            i.execute({'name': name, 'memory_mb': values["mem"],
                        'vcpus': values["vcpus"], 'deleted': False,
                        'root_gb': values["root_gb"],
                        'ephemeral_gb': values["eph_gb"],
                        'rxtx_factor': 1,
                        'swap': 0,
                        'flavorid': values["flavid"],
                        'disabled': False,
                        'is_public': True})
    except Exception:
        LOG.info(repr(instance_types_table))
        LOG.exception(_('Exception while seeding instance_types table'))
        raise


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    agent_builds = Table('agent_builds', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('hypervisor', String(length=255)),
        Column('os', String(length=255)),
        Column('architecture', String(length=255)),
        Column('version', String(length=255)),
        Column('url', String(length=255)),
        Column('md5hash', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_hosts = Table('aggregate_hosts', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('aggregate_id', Integer, ForeignKey('aggregates.id'),
              nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_metadata = Table('aggregate_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('aggregate_id', Integer, ForeignKey('aggregates.id'),
              nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregates = Table('aggregates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('availability_zone', String(length=255), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    block_device_mapping = Table('block_device_mapping', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('device_name', String(length=255), nullable=False),
        Column('delete_on_termination', Boolean),
        Column('virtual_name', String(length=255)),
        Column('snapshot_id', String(length=36), nullable=True),
        Column('volume_id', String(length=36), nullable=True),
        Column('volume_size', Integer),
        Column('no_device', Boolean),
        Column('connection_info', MediumText()),
        Column('instance_uuid', String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    bw_usage_cache = Table('bw_usage_cache', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('start_period', DateTime, nullable=False),
        Column('last_refreshed', DateTime),
        Column('bw_in', BigInteger),
        Column('bw_out', BigInteger),
        Column('mac', String(length=255)),
        Column('uuid', String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    cells = Table('cells', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('api_url', String(length=255)),
        Column('username', String(length=255)),
        Column('password', String(length=255)),
        Column('weight_offset', Float),
        Column('weight_scale', Float),
        Column('name', String(length=255)),
        Column('is_parent', Boolean),
        Column('rpc_host', String(length=255)),
        Column('rpc_port', Integer),
        Column('rpc_virtual_host', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    certificates = Table('certificates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('file_name', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    compute_node_stats = Table('compute_node_stats', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('compute_node_id', Integer, nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    compute_nodes = Table('compute_nodes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('service_id', Integer, nullable=False),
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
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    console_pools = Table('console_pools', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255)),
        Column('username', String(length=255)),
        Column('password', String(length=255)),
        Column('console_type', String(length=255)),
        Column('public_hostname', String(length=255)),
        Column('host', String(length=255)),
        Column('compute_host', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    consoles = Table('consoles', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_name', String(length=255)),
        Column('password', String(length=255)),
        Column('port', Integer),
        Column('pool_id', Integer, ForeignKey('console_pools.id')),
        Column('instance_uuid', String(length=36)),
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
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255)),
        Column('network_id', Integer),
        Column('allocated', Boolean),
        Column('leased', Boolean),
        Column('reserved', Boolean),
        Column('virtual_interface_id', Integer),
        Column('host', String(length=255)),
        Column('instance_uuid', String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    floating_ips = Table('floating_ips', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255)),
        Column('fixed_ip_id', Integer),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('auto_assigned', Boolean),
        Column('pool', String(length=255)),
        Column('interface', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_faults = Table('instance_faults', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=36)),
        Column('code', Integer, nullable=False),
        Column('message', String(length=255)),
        Column('details', MediumText()),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_id_mappings = Table('instance_id_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(36), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_info_caches = Table('instance_info_caches', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('network_info', MediumText()),
        Column('instance_uuid', String(length=36), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_metadata = Table('instance_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        Column('instance_uuid', String(length=36), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_system_metadata = Table('instance_system_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=36), nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_type_extra_specs = Table('instance_type_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_type_id', Integer, ForeignKey('instance_types.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_type_projects = Table('instance_type_projects', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_type_id', Integer, nullable=False),
        Column('project_id', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_types = Table('instance_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
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
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instances = Table('instances', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('internal_id', Integer),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('image_ref', String(length=255)),
        Column('kernel_id', String(length=255)),
        Column('ramdisk_id', String(length=255)),
        Column('server_name', String(length=255)),
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
        Column('scheduled_at', DateTime),
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
        Column('uuid', String(length=36)),
        Column('architecture', String(length=255)),
        Column('root_device_name', String(length=255)),
        Column('access_ip_v4', String(length=255)),
        Column('access_ip_v6', String(length=255)),
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
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    iscsi_targets = Table('iscsi_targets', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('target_num', Integer),
        Column('host', String(length=255)),
        Column('volume_id', String(length=36), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    key_pairs = Table('key_pairs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('user_id', String(length=255)),
        Column('fingerprint', String(length=255)),
        Column('public_key', MediumText()),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    migrations = Table('migrations', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('source_compute', String(length=255)),
        Column('dest_compute', String(length=255)),
        Column('dest_host', String(length=255)),
        Column('status', String(length=255)),
        Column('instance_uuid', String(length=255)),
        Column('old_instance_type_id', Integer),
        Column('new_instance_type_id', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    networks = Table('networks', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('injected', Boolean),
        Column('cidr', String(length=255)),
        Column('netmask', String(length=255)),
        Column('bridge', String(length=255)),
        Column('gateway', String(length=255)),
        Column('broadcast', String(length=255)),
        Column('dns1', String(length=255)),
        Column('vlan', Integer),
        Column('vpn_public_address', String(length=255)),
        Column('vpn_public_port', Integer),
        Column('vpn_private_address', String(length=255)),
        Column('dhcp_start', String(length=255)),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('cidr_v6', String(length=255)),
        Column('gateway_v6', String(length=255)),
        Column('label', String(length=255)),
        Column('netmask_v6', String(length=255)),
        Column('bridge_interface', String(length=255)),
        Column('multi_host', Boolean),
        Column('dns2', String(length=255)),
        Column('uuid', String(length=36)),
        Column('priority', Integer),
        Column('rxtx_base', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    provider_fw_rules = Table('provider_fw_rules', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('protocol', String(length=5)),
        Column('from_port', Integer),
        Column('to_port', Integer),
        Column('cidr', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_classes = Table('quota_classes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('class_name', String(length=255)),
        Column('resource', String(length=255)),
        Column('hard_limit', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quota_usages = Table('quota_usages', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255)),
        Column('in_use', Integer, nullable=False),
        Column('reserved', Integer, nullable=False),
        Column('until_refresh', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    quotas = Table('quotas', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255), nullable=False),
        Column('hard_limit', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    reservations = Table('reservations', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('usage_id', Integer, nullable=False),
        Column('project_id', String(length=255)),
        Column('resource', String(length=255)),
        Column('delta', Integer, nullable=False),
        Column('expire', DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    s3_images = Table('s3_images', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_instance_association = \
        Table('security_group_instance_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('security_group_id', Integer, ForeignKey('security_groups.id')),
        Column('instance_uuid', String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_group_rules = Table('security_group_rules', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('parent_group_id', Integer, ForeignKey('security_groups.id')),
        Column('protocol', String(length=255)),
        Column('from_port', Integer),
        Column('to_port', Integer),
        Column('cidr', String(length=255)),
        Column('group_id', Integer, ForeignKey('security_groups.id')),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    security_groups = Table('security_groups', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('description', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    services = Table('services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('binary', String(length=255)),
        Column('topic', String(length=255)),
        Column('report_count', Integer, nullable=False),
        Column('disabled', Boolean),
        Column('availability_zone', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_backend_config = Table('sm_backend_config', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, ForeignKey('sm_flavors.id'),
               nullable=False),
        Column('sr_uuid', String(length=255)),
        Column('sr_type', String(length=255)),
        Column('config_params', String(length=2047)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_flavors = Table('sm_flavors', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('label', String(length=255)),
        Column('description', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_volume = Table('sm_volume', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=36), primary_key=True,
                  nullable=False, autoincrement=False),
        Column('backend_id', Integer, nullable=False),
        Column('vdi_uuid', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshot_id_mappings = Table('snapshot_id_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshots = Table('snapshots', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
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
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    task_log = Table('task_log', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('task_name', String(length=255), nullable=False),
        Column('state', String(length=255), nullable=False),
        Column('host', String(length=255), nullable=False),
        Column('period_beginning', String(length=255), nullable=False),
        Column('period_ending', String(length=255), nullable=False),
        Column('message', String(length=255), nullable=False),
        Column('task_items', Integer),
        Column('errors', Integer),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    virtual_interfaces = Table('virtual_interfaces', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255), unique=True),
        Column('network_id', Integer),
        Column('uuid', String(length=36)),
        Column('instance_uuid', String(length=36), nullable=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    virtual_storage_arrays = Table('virtual_storage_arrays', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('project_id', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('instance_type_id', Integer, nullable=False),
        Column('image_ref', String(length=255)),
        Column('vc_count', Integer, nullable=False),
        Column('vol_count', Integer, nullable=False),
        Column('status', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_id_mappings = Table('volume_id_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_metadata = Table('volume_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', String(length=36), nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_type_extra_specs = Table('volume_type_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_type_id', Integer, ForeignKey('volume_types.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_types = Table('volume_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volumes = Table('volumes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=36), primary_key=True, nullable=False),
        Column('ec2_id', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('size', Integer),
        Column('availability_zone', String(length=255)),
        Column('mountpoint', String(length=255)),
        Column('status', String(length=255)),
        Column('attach_status', String(length=255)),
        Column('scheduled_at', DateTime),
        Column('launched_at', DateTime),
        Column('terminated_at', DateTime),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('provider_location', String(length=256)),
        Column('provider_auth', String(length=256)),
        Column('snapshot_id', String(length=36)),
        Column('volume_type_id', Integer),
        Column('instance_uuid', String(length=36)),
        Column('attach_time', DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instances.create()
    Index('uuid', instances.c.uuid, unique=True).create(migrate_engine)
    Index('project_id', instances.c.project_id).create(migrate_engine)

    # create all tables
    tables = [aggregates, console_pools, instance_types,
              security_groups, sm_flavors, sm_backend_config,
              snapshots, volume_types,
              volumes,
              # those that are children and others later
              agent_builds, aggregate_hosts, aggregate_metadata,
              block_device_mapping, bw_usage_cache, cells,
              certificates, compute_node_stats, compute_nodes, consoles,
              dns_domains, fixed_ips, floating_ips,
              instance_faults, instance_id_mappings, instance_info_caches,
              instance_metadata, instance_system_metadata,
              instance_type_extra_specs, instance_type_projects,
              iscsi_targets, key_pairs, migrations, networks,
              provider_fw_rules, quota_classes, quota_usages, quotas,
              reservations, s3_images, security_group_instance_association,
              security_group_rules, services, sm_volume,
              snapshot_id_mappings, task_log,
              virtual_interfaces,
              virtual_storage_arrays, volume_id_mappings, volume_metadata,
              volume_type_extra_specs]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception(_('Exception while creating table.'))
            raise

    indexes = [
        # agent_builds
        Index('agent_builds_hypervisor_os_arch_idx',
              agent_builds.c.hypervisor,
              agent_builds.c.os,
              agent_builds.c.architecture),

        # aggregate_metadata
        Index('aggregate_metadata_key_idx', aggregate_metadata.c.key),

        # block_device_mapping
        Index('block_device_mapping_instance_uuid_idx',
              block_device_mapping.c.instance_uuid),

        Index('block_device_mapping_instance_uuid_device_name_idx',
              block_device_mapping.c.instance_uuid,
              block_device_mapping.c.device_name),
        Index(
             'block_device_mapping_instance_uuid_virtual_name_device_name_idx',
             block_device_mapping.c.instance_uuid,
             block_device_mapping.c.virtual_name,
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

        Index('certificates_user_id_deleted_idx',
              certificates.c.user_id, certificates.c.deleted),

        # compute_node_stats
        Index('ix_compute_node_stats_compute_node_id',
              compute_node_stats.c.compute_node_id),

        # consoles
        Index('consoles_instance_uuid_idx', consoles.c.instance_uuid),

        # dns_domains
        Index('dns_domains_domain_deleted_idx',
              dns_domains.c.domain, dns_domains.c.deleted),

        # fixed_ips
        Index('fixed_ips_host_idx', fixed_ips.c.host),
        Index('fixed_ips_network_id_host_deleted_idx',
              fixed_ips.c.network_id, fixed_ips.c.host, fixed_ips.c.deleted),
        Index('fixed_ips_address_reserved_network_id_deleted_idx',
              fixed_ips.c.address, fixed_ips.c.reserved,
              fixed_ips.c.network_id, fixed_ips.c.deleted),

        # floating_ips
        Index('floating_ips_host_idx', floating_ips.c.host),

        Index('floating_ips_project_id_idx', floating_ips.c.project_id),

        Index('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
              floating_ips.c.pool, floating_ips.c.deleted,
              floating_ips.c.fixed_ip_id, floating_ips.c.project_id),

        # instance_faults
        Index('instance_faults_instance_uuid_deleted_created_at_idx',
              instance_faults.c.instance_uuid, instance_faults.c.deleted,
              instance_faults.c.created_at),

        # instance_type_extra_specs
        Index('instance_type_extra_specs_instance_type_id_key_idx',
              instance_type_extra_specs.c.instance_type_id,
              instance_type_extra_specs.c.key),

        # instance_id_mappings
        Index('ix_instance_id_mappings_uuid', instance_id_mappings.c.uuid),

        # instance_metadata
        Index('instance_metadata_instance_uuid_idx',
              instance_metadata.c.instance_uuid),

        # instances
        Index('instances_host_deleted_idx',
              instances.c.host, instances.c.deleted),

        Index('instances_reservation_id_idx', instances.c.reservation_id),

        Index('instances_terminated_at_launched_at_idx',
              instances.c.terminated_at, instances.c.launched_at),

        Index('instances_uuid_deleted_idx',
              instances.c.uuid, instances.c.deleted),

        Index('instances_task_state_updated_at_idx',
              instances.c.task_state, instances.c.updated_at),


        # iscsi_targets
        Index('iscsi_targets_host_idx', iscsi_targets.c.host),

        Index('iscsi_targets_host_volume_id_deleted_idx',
              iscsi_targets.c.host, iscsi_targets.c.volume_id,
              iscsi_targets.c.deleted),

        # key_pairs
        Index('key_pair_user_id_name_idx',
              key_pairs.c.user_id, key_pairs.c.name),

        # networks
        Index('networks_bridge_deleted_idx',
              networks.c.bridge, networks.c.deleted),

        Index('networks_host_idx', networks.c.host),

        Index('networks_project_id_deleted_idx',
              networks.c.project_id, networks.c.deleted),

        Index('networks_uuid_project_id_deleted_idx',
              networks.c.uuid, networks.c.project_id, networks.c.deleted),

        Index('networks_vlan_deleted_idx',
              networks.c.vlan, networks.c.deleted),

        Index('networks_cidr_v6_idx', networks.c.cidr_v6),

        # reservations
        Index('ix_reservations_project_id', reservations.c.project_id),

        # security_group_instance_association
        Index('security_group_instance_association_instance_uuid_idx',
              security_group_instance_association.c.instance_uuid),

        # quota_classes
        Index('ix_quota_classes_class_name', quota_classes.c.class_name),

        # quota_usages
        Index('ix_quota_usages_project_id', quota_usages.c.project_id),


        # volumes
        Index('volumes_instance_uuid_idx', volumes.c.instance_uuid),

        # task_log
        Index('ix_task_log_period_beginning', task_log.c.period_beginning),
        Index('ix_task_log_host', task_log.c.host),
        Index('ix_task_log_period_ending', task_log.c.period_ending),

    ]

    mysql_indexes = [
        # TODO(dprince): review these for removal. Some of these indexes
        # were automatically created by SQLAlchemy migrate and *may* no longer
        # be in use
        Index('instance_type_id', instance_type_projects.c.instance_type_id),
        Index('project_id', dns_domains.c.project_id),
        Index('fixed_ip_id', floating_ips.c.fixed_ip_id),
        Index('backend_id', sm_volume.c.backend_id),
        Index('network_id', virtual_interfaces.c.network_id),
        Index('network_id', fixed_ips.c.network_id),
        Index('fixed_ips_virtual_interface_id_fkey',
                  fixed_ips.c.virtual_interface_id),
        Index('address', fixed_ips.c.address),
        Index('fixed_ips_instance_uuid_fkey', fixed_ips.c.instance_uuid),
        Index('instance_uuid', instance_system_metadata.c.instance_uuid),
        Index('iscsi_targets_volume_id_fkey', iscsi_targets.c.volume_id),
        Index('snapshot_id', block_device_mapping.c.snapshot_id),
        Index('usage_id', reservations.c.usage_id),
        Index('virtual_interfaces_instance_uuid_fkey',
              virtual_interfaces.c.instance_uuid),
        Index('volume_id', block_device_mapping.c.volume_id),
        Index('volume_metadata_volume_id_fkey', volume_metadata.c.volume_id),
    ]

    # MySQL specific indexes
    if migrate_engine.name == 'mysql':
        for index in mysql_indexes:
            index.create(migrate_engine)

    # PostgreSQL specific indexes
    if migrate_engine.name == 'postgresql':
        Index('address', fixed_ips.c.address).create()

    # Common indexes
    if migrate_engine.name == 'mysql' or migrate_engine.name == 'postgresql':
        for index in indexes:
            index.create(migrate_engine)

    fkeys = [

              [[fixed_ips.c.instance_uuid],
                  [instances.c.uuid],
                  'fixed_ips_instance_uuid_fkey'],
              [[block_device_mapping.c.instance_uuid],
                  [instances.c.uuid],
                  'block_device_mapping_instance_uuid_fkey'],
              [[consoles.c.instance_uuid],
                  [instances.c.uuid],
                  'consoles_instance_uuid_fkey'],
              [[instance_info_caches.c.instance_uuid],
                  [instances.c.uuid],
                  'instance_info_caches_instance_uuid_fkey'],
              [[instance_metadata.c.instance_uuid],
                  [instances.c.uuid],
                  'instance_metadata_instance_uuid_fkey'],
              [[instance_system_metadata.c.instance_uuid],
                  [instances.c.uuid],
                  'instance_system_metadata_ibfk_1'],
              [[instance_type_projects.c.instance_type_id],
                  [instance_types.c.id],
                  'instance_type_projects_ibfk_1'],
              [[iscsi_targets.c.volume_id],
                  [volumes.c.id],
                  'iscsi_targets_volume_id_fkey'],
              [[reservations.c.usage_id],
                  [quota_usages.c.id],
                  'reservations_ibfk_1'],
              [[security_group_instance_association.c.instance_uuid],
                  [instances.c.uuid],
                  'security_group_instance_association_instance_uuid_fkey'],
              [[sm_volume.c.backend_id],
                  [sm_backend_config.c.id],
                  'sm_volume_ibfk_2'],
              [[sm_volume.c.id],
                  [volumes.c.id],
                  'sm_volume_id_fkey'],
              [[virtual_interfaces.c.instance_uuid],
                  [instances.c.uuid],
                  'virtual_interfaces_instance_uuid_fkey'],
              [[volume_metadata.c.volume_id],
                  [volumes.c.id],
                  'volume_metadata_volume_id_fkey'],

            ]

    for fkey_pair in fkeys:
        if migrate_engine.name == 'mysql':
            # For MySQL we name our fkeys explicitly so they match Folsom
            fkey = ForeignKeyConstraint(columns=fkey_pair[0],
                                   refcolumns=fkey_pair[1],
                                   name=fkey_pair[2])
            fkey.create()
        elif migrate_engine.name == 'postgresql':
            # PostgreSQL names things like it wants (correct and compatible!)
            fkey = ForeignKeyConstraint(columns=fkey_pair[0],
                                   refcolumns=fkey_pair[1])
            fkey.create()

    if migrate_engine.name == "mysql":
        # In Folsom we explicitly converted migrate_version to UTF8.
        sql = "ALTER TABLE migrate_version CONVERT TO CHARACTER SET utf8;"
        # Set default DB charset to UTF8.
        sql += "ALTER DATABASE %s DEFAULT CHARACTER SET utf8;" % \
                migrate_engine.url.database
        migrate_engine.execute(sql)

        # TODO(dprince): due to the upgrade scripts in Folsom the unique key
        # on instance_uuid is named 'instance_id'. Rename it in Grizzly?
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name='instance_id').create()

    if migrate_engine.name == "postgresql":
        # TODO(dprince): Drop this in Grizzly. Snapshots were converted
        # to UUIDs in Folsom so we no longer require this autocreated
        # sequence.
        sql = """CREATE SEQUENCE snapshots_id_seq START WITH 1 INCREMENT BY 1
              NO MINVALUE NO MAXVALUE CACHE 1;
              ALTER SEQUENCE snapshots_id_seq OWNED BY snapshots.id;
              SELECT pg_catalog.setval('snapshots_id_seq', 1, false);
              ALTER TABLE ONLY snapshots ALTER COLUMN id SET DEFAULT
              nextval('snapshots_id_seq'::regclass);"""

        # TODO(dprince): Drop this in Grizzly. Volumes were converted
        # to UUIDs in Folsom so we no longer require this autocreated
        # sequence.
        sql += """CREATE SEQUENCE volumes_id_seq START WITH 1 INCREMENT BY 1
               NO MINVALUE NO MAXVALUE CACHE 1;
               ALTER SEQUENCE volumes_id_seq OWNED BY volumes.id;
               SELECT pg_catalog.setval('volumes_id_seq', 1, false);
               ALTER TABLE ONLY volumes ALTER COLUMN id SET DEFAULT
               nextval('volumes_id_seq'::regclass);"""

        migrate_engine.execute(sql)

        # TODO(dprince): due to the upgrade scripts in Folsom the unique key
        # on instance_uuid is named '.._instance_id_..'. Rename it in Grizzly?
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name='instance_info_caches_instance_id_key').create()

    # populate initial instance types
    _populate_instance_types(instance_types)


def downgrade(migrate_engine):
    raise NotImplementedError('Downgrade from Folsom is unsupported.')
