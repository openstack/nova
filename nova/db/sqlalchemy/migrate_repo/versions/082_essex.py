# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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
from sqlalchemy import Boolean, BigInteger, Column, DateTime, Float, ForeignKey
from sqlalchemy import Index, Integer, MetaData, String, Table, Text

from nova import flags
from nova.openstack.common import log as logging

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


# Note on the autoincrement flag: this is defaulted for primary key columns
# of integral type, so is no longer set explicitly in such cases.

def _populate_instance_types(instance_types_table):
    if FLAGS.connection_type == "libvirt":
        default_inst_types = {
        'm1.tiny': dict(mem=512, vcpus=1, root_gb=0, eph_gb=0, flavid=1),
        'm1.small': dict(mem=2048, vcpus=1, root_gb=10, eph_gb=20, flavid=2),
        'm1.medium': dict(mem=4096, vcpus=2, root_gb=10, eph_gb=40, flavid=3),
        'm1.large': dict(mem=8192, vcpus=4, root_gb=10, eph_gb=80, flavid=4),
        'm1.xlarge': dict(mem=16384, vcpus=8, root_gb=10, eph_gb=160, flavid=5)
        }
    else:
        default_inst_types = {
        'm1.tiny': dict(mem=512, vcpus=1, root_gb=0, eph_gb=0, flavid=1),
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
                        'flavorid': values["flavid"]})
    except Exception:
        LOG.info(repr(instance_types_table))
        LOG.exception('Exception while seeding instance_types table')
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
        #mysql_charset='utf8'
    )

    aggregate_hosts = Table('aggregate_hosts', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255), unique=True),
        Column('aggregate_id', Integer, ForeignKey('aggregates.id'),
              nullable=False),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    aggregates = Table('aggregates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255), unique=True),
        Column('operational_state', String(length=255), nullable=False),
        Column('availability_zone', String(length=255), nullable=False),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    auth_tokens = Table('auth_tokens', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('token_hash', String(length=255), primary_key=True,
               nullable=False),
        Column('user_id', String(length=255)),
        Column('server_management_url', String(length=255)),
        Column('storage_url', String(length=255)),
        Column('cdn_management_url', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    block_device_mapping = Table('block_device_mapping', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_id', Integer, ForeignKey('instances.id'),
               nullable=False),
        Column('device_name', String(length=255), nullable=False),
        Column('delete_on_termination', Boolean),
        Column('virtual_name', String(length=255)),
        Column('snapshot_id', Integer, ForeignKey('snapshots.id'),
               nullable=True),
        Column('volume_id', Integer(), ForeignKey('volumes.id'),
               nullable=True),
        Column('volume_size', Integer),
        Column('no_device', Boolean),
        Column('connection_info', Text),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        Column('hypervisor_type', Text, nullable=False),
        Column('hypervisor_version', Integer, nullable=False),
        Column('cpu_info', Text, nullable=False),
        Column('disk_available_least', Integer),
        Column('free_ram_mb', Integer),
        Column('free_disk_gb', Integer),
        Column('current_workload', Integer),
        Column('running_vms', Integer),
        Column('hypervisor_hostname', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    consoles = Table('consoles', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_name', String(length=255)),
        Column('instance_id', Integer),
        Column('password', String(length=255)),
        Column('port', Integer),
        Column('pool_id', Integer, ForeignKey('console_pools.id')),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    # NOTE(dprince): Trying to create a fresh utf8 dns_domains tables
    # with a domain primary key length of 512 fails w/
    # 'Specified key was too long; max key length is 767 bytes'.
    # See:  https://bugs.launchpad.net/nova/+bug/993663
    # If we fix this during Folsom we can set mysql_charset=utf8 inline...
    # and remove the unsightly loop that does it below during "E" compaction.
    dns_domains = Table('dns_domains', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('domain', String(length=512), primary_key=True, nullable=False),
        Column('scope', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('project_id', String(length=255), ForeignKey('projects.id')),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    fixed_ips = Table('fixed_ips', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255)),
        Column('network_id', Integer),
        Column('instance_id', Integer),
        Column('allocated', Boolean),
        Column('leased', Boolean),
        Column('reserved', Boolean),
        Column('virtual_interface_id', Integer),
        Column('host', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    instance_actions = Table('instance_actions', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('action', String(length=255)),
        Column('error', Text),
        Column('instance_uuid', String(length=36)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        Column('details', Text),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    instance_info_caches = Table('instance_info_caches', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('network_info', Text),
        Column('instance_id', String(36), nullable=False, unique=True),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    instance_metadata = Table('instance_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_id', Integer, ForeignKey('instances.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        Column('key_data', Text),
        Column('power_state', Integer),
        Column('vm_state', String(length=255)),
        Column('memory_mb', Integer),
        Column('vcpus', Integer),
        Column('hostname', String(length=255)),
        Column('host', String(length=255)),
        Column('user_data', Text),
        Column('reservation_id', String(length=255)),
        Column('scheduled_at', DateTime),
        Column('launched_at', DateTime),
        Column('terminated_at', DateTime),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('locked', Boolean),
        Column('os_type', String(length=255)),
        Column('launched_on', Text),
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
        #mysql_charset='utf8'
    )

    iscsi_targets = Table('iscsi_targets', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('target_num', Integer),
        Column('host', String(length=255)),
        Column('volume_id', Integer, ForeignKey('volumes.id'),
               nullable=True),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        Column('public_key', Text),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    projects = Table('projects', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('description', String(length=255)),
        Column('project_manager', String(length=255), ForeignKey('users.id')),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    s3_images = Table('s3_images', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    security_group_instance_association = \
        Table('security_group_instance_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('security_group_id', Integer, ForeignKey('security_groups.id')),
        Column('instance_id', Integer, ForeignKey('instances.id')),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    sm_volume = Table('sm_volume', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer(), ForeignKey('volumes.id'), primary_key=True,
                  nullable=False, autoincrement=False),
        Column('backend_id', Integer, ForeignKey('sm_backend_config.id'),
               nullable=False),
        Column('vdi_uuid', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    snapshots = Table('snapshots', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', Integer, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('status', String(length=255)),
        Column('progress', String(length=255)),
        Column('volume_size', Integer),
        Column('scheduled_at', DateTime),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    user_project_association = Table('user_project_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('user_id', String(length=255), primary_key=True,
               nullable=False),
        Column('project_id', String(length=255), primary_key=True,
               nullable=False),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    user_project_role_association = \
        Table('user_project_role_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('user_id', String(length=255), primary_key=True,
               nullable=False),
        Column('project_id', String(length=255), primary_key=True,
               nullable=False),
        Column('role', String(length=255), primary_key=True, nullable=False),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    user_role_association = Table('user_role_association', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('user_id', String(length=255), ForeignKey('users.id'),
               primary_key=True, nullable=False),
        Column('role', String(length=255), primary_key=True, nullable=False),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    users = Table('users', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('access_key', String(length=255)),
        Column('secret_key', String(length=255)),
        Column('is_admin', Boolean),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    virtual_interfaces = Table('virtual_interfaces', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('address', String(length=255), unique=True),
        Column('network_id', Integer),
        Column('instance_id', Integer, nullable=False),
        Column('uuid', String(length=36)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    volume_types = Table('volume_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    volume_metadata = Table('volume_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', Integer, ForeignKey('volumes.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
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
        #mysql_charset='utf8'
    )

    volumes = Table('volumes', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('ec2_id', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('size', Integer),
        Column('availability_zone', String(length=255)),
        Column('instance_id', Integer, ForeignKey('instances.id')),
        Column('mountpoint', String(length=255)),
        Column('attach_time', String(length=255)),
        Column('status', String(length=255)),
        Column('attach_status', String(length=255)),
        Column('scheduled_at', DateTime),
        Column('launched_at', DateTime),
        Column('terminated_at', DateTime),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('provider_location', String(length=256)),
        Column('provider_auth', String(length=256)),
        Column('snapshot_id', Integer),
        Column('volume_type_id', Integer),
        mysql_engine='InnoDB',
        #mysql_charset='utf8'
    )

    instances.create()
    Index('uuid', instances.c.uuid, unique=True).create(migrate_engine)
    Index('project_id', instances.c.project_id).create(migrate_engine)

    # create all tables
    tables = [aggregates, console_pools, instance_types,
              users, projects, security_groups, sm_flavors, sm_backend_config,
              snapshots, user_project_association, volume_types,
              volumes,
              # those that are children and others later
              agent_builds, aggregate_hosts, aggregate_metadata,
              auth_tokens, block_device_mapping, bw_usage_cache, cells,
              certificates, compute_nodes, consoles, dns_domains, fixed_ips,
              floating_ips, instance_actions, instance_faults,
              instance_info_caches, instance_metadata,
              instance_type_extra_specs, iscsi_targets, key_pairs,
              migrations, networks, provider_fw_rules,
              quotas, s3_images, security_group_instance_association,
              security_group_rules, services, sm_volume,
              user_project_role_association, user_role_association,
              virtual_interfaces, virtual_storage_arrays, volume_metadata,
              volume_type_extra_specs]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception('Exception while creating table.')
            raise

    # MySQL specific Indexes from Essex
    # NOTE(dprince): I think some of these can be removed in Folsom
    indexes = [
        Index('network_id', fixed_ips.c.network_id),
        Index('instance_id', fixed_ips.c.instance_id),
        Index('fixed_ips_virtual_interface_id_fkey',
                  fixed_ips.c.virtual_interface_id),
        Index('fixed_ip_id', floating_ips.c.fixed_ip_id),
        Index('project_id', user_project_association.c.project_id),
        Index('network_id', virtual_interfaces.c.network_id),
        Index('instance_id', virtual_interfaces.c.instance_id),
    ]

    if migrate_engine.name == 'mysql':
        for index in indexes:
            index.create(migrate_engine)

    fkeys = [
              [[user_project_role_association.c.user_id,
                      user_project_role_association.c.project_id],
                  [user_project_association.c.user_id,
                      user_project_association.c.project_id],
                  'user_project_role_association_ibfk_1'],
              [[user_project_association.c.user_id],
                  [users.c.id], 'user_project_association_ibfk_1'],
              [[user_project_association.c.project_id], [projects.c.id],
                  'user_project_association_ibfk_2'],
              [[instance_info_caches.c.instance_id], [instances.c.uuid],
                  'instance_info_caches_ibfk_1'],
            ]

    for fkey_pair in fkeys:
        if migrate_engine.name == 'mysql':
            # For MySQL we name our fkeys explicitly so they match Essex
            fkey = ForeignKeyConstraint(columns=fkey_pair[0],
                                   refcolumns=fkey_pair[1],
                                   name=fkey_pair[2])
            fkey.create()
        elif migrate_engine.name == 'postgresql':
            fkey = ForeignKeyConstraint(columns=fkey_pair[0],
                                   refcolumns=fkey_pair[1])
            fkey.create()

    # Hopefully this entire loop to set the charset can go away during
    # the "E" release compaction. See the notes on the dns_domains
    # table above for why this is required vs. setting mysql_charset inline.
    if migrate_engine.name == "mysql":
        tables = [
            # tables that are FK parents, must be converted early
            "aggregates", "console_pools", "instance_types", "instances",
            "projects", "security_groups", "sm_backend_config", "sm_flavors",
            "snapshots", "user_project_association", "users", "volume_types",
            "volumes",
            # those that are children and others later
            "agent_builds", "aggregate_hosts", "aggregate_metadata",
            "auth_tokens", "block_device_mapping", "bw_usage_cache",
            "certificates", "compute_nodes", "consoles", "fixed_ips",
            "floating_ips", "instance_actions", "instance_faults",
            "instance_info_caches", "instance_metadata",
            "instance_type_extra_specs", "iscsi_targets", "key_pairs",
            "migrate_version", "migrations", "networks", "provider_fw_rules",
            "quotas", "s3_images", "security_group_instance_association",
            "security_group_rules", "services", "sm_volume",
            "user_project_role_association", "user_role_association",
            "virtual_interfaces", "virtual_storage_arrays", "volume_metadata",
            "volume_type_extra_specs"]
        sql = "SET foreign_key_checks = 0;"
        for table in tables:
            sql += "ALTER TABLE %s CONVERT TO CHARACTER SET utf8;" % table
        sql += "SET foreign_key_checks = 1;"
        sql += "ALTER DATABASE %s DEFAULT CHARACTER SET utf8;" \
            % migrate_engine.url.database
        migrate_engine.execute(sql)

    if migrate_engine.name == "postgresql":
        # NOTE(dprince): Need to rename the leftover zones stuff.
        # https://bugs.launchpad.net/nova/+bug/993667
        sql = "ALTER TABLE cells_id_seq RENAME TO zones_id_seq;"
        sql += "ALTER TABLE ONLY cells DROP CONSTRAINT cells_pkey;"
        sql += "ALTER TABLE ONLY cells ADD CONSTRAINT zones_pkey" \
                   " PRIMARY KEY (id);"

        # NOTE(dprince): Need to rename the leftover quota_new stuff.
        # https://bugs.launchpad.net/nova/+bug/993669
        sql += "ALTER TABLE quotas_id_seq RENAME TO quotas_new_id_seq;"
        sql += "ALTER TABLE ONLY quotas DROP CONSTRAINT quotas_pkey;"
        sql += "ALTER TABLE ONLY quotas ADD CONSTRAINT quotas_new_pkey" \
                   " PRIMARY KEY (id);"

        migrate_engine.execute(sql)

    # populate initial instance types
    _populate_instance_types(instance_types)


def downgrade(migrate_engine):
    raise Exception('Downgrade from Essex is unsupported.')
