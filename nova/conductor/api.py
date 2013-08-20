#    Copyright 2012 IBM Corp.
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

"""Handles all requests to the conductor service."""

from oslo.config import cfg

from nova import baserpc
from nova.conductor import manager
from nova.conductor import rpcapi
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import common as rpc_common
from nova import utils

conductor_opts = [
    cfg.BoolOpt('use_local',
                default=False,
                help='Perform nova-conductor operations locally'),
    cfg.StrOpt('topic',
               default='conductor',
               help='the topic conductor nodes listen on'),
    cfg.StrOpt('manager',
               default='nova.conductor.manager.ConductorManager',
               help='full class name for the Manager for conductor'),
]
conductor_group = cfg.OptGroup(name='conductor',
                               title='Conductor Options')
CONF = cfg.CONF
CONF.register_group(conductor_group)
CONF.register_opts(conductor_opts, conductor_group)

LOG = logging.getLogger(__name__)


class LocalAPI(object):
    """A local version of the conductor API that does database updates
    locally instead of via RPC.
    """

    def __init__(self):
        # TODO(danms): This needs to be something more generic for
        # other/future users of this sort of functionality.
        self._manager = utils.ExceptionHelper(manager.ConductorManager())

    def wait_until_ready(self, context, *args, **kwargs):
        # nothing to wait for in the local case.
        pass

    def instance_update(self, context, instance_uuid, **updates):
        """Perform an instance update in the database."""
        return self._manager.instance_update(context, instance_uuid,
                                             updates, 'compute')

    def instance_get(self, context, instance_id):
        return self._manager.instance_get(context, instance_id)

    def instance_get_by_uuid(self, context, instance_uuid,
                             columns_to_join=None):
        return self._manager.instance_get_by_uuid(context, instance_uuid,
                columns_to_join)

    def instance_destroy(self, context, instance):
        return self._manager.instance_destroy(context, instance)

    def instance_get_all_by_host(self, context, host, columns_to_join=None):
        return self._manager.instance_get_all_by_host(
            context, host, columns_to_join=columns_to_join)

    def instance_get_all_by_host_and_node(self, context, host, node):
        return self._manager.instance_get_all_by_host(context, host, node)

    def instance_get_all_by_filters(self, context, filters,
                                    sort_key='created_at',
                                    sort_dir='desc',
                                    columns_to_join=None):
        return self._manager.instance_get_all_by_filters(context,
                                                         filters,
                                                         sort_key,
                                                         sort_dir,
                                                         columns_to_join)

    def instance_get_active_by_window_joined(self, context, begin, end=None,
                                             project_id=None, host=None):
        return self._manager.instance_get_active_by_window_joined(
            context, begin, end, project_id, host)

    def instance_info_cache_update(self, context, instance, values):
        return self._manager.instance_info_cache_update(context,
                                                        instance,
                                                        values)

    def instance_info_cache_delete(self, context, instance):
        return self._manager.instance_info_cache_delete(context, instance)

    def instance_type_get(self, context, instance_type_id):
        return self._manager.instance_type_get(context, instance_type_id)

    def instance_fault_create(self, context, values):
        return self._manager.instance_fault_create(context, values)

    def migration_get(self, context, migration_id):
        return self._manager.migration_get(context, migration_id)

    def migration_get_unconfirmed_by_dest_compute(self, context,
                                                  confirm_window,
                                                  dest_compute):
        return self._manager.migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute)

    def migration_get_in_progress_by_host_and_node(self, context, host, node):
        return self._manager.migration_get_in_progress_by_host_and_node(
            context, host, node)

    def migration_create(self, context, instance, values):
        return self._manager.migration_create(context, instance, values)

    def migration_update(self, context, migration, status):
        return self._manager.migration_update(context, migration, status)

    def aggregate_host_add(self, context, aggregate, host):
        return self._manager.aggregate_host_add(context, aggregate, host)

    def aggregate_host_delete(self, context, aggregate, host):
        return self._manager.aggregate_host_delete(context, aggregate, host)

    def aggregate_get(self, context, aggregate_id):
        return self._manager.aggregate_get(context, aggregate_id)

    def aggregate_get_by_host(self, context, host, key=None):
        return self._manager.aggregate_get_by_host(context, host, key)

    def aggregate_metadata_add(self, context, aggregate, metadata,
                               set_delete=False):
        return self._manager.aggregate_metadata_add(context, aggregate,
                                                    metadata,
                                                    set_delete)

    def aggregate_metadata_delete(self, context, aggregate, key):
        return self._manager.aggregate_metadata_delete(context,
                                                       aggregate,
                                                       key)

    def aggregate_metadata_get_by_host(self, context, host,
                                       key='availability_zone'):
        return self._manager.aggregate_metadata_get_by_host(context,
                                                            host,
                                                            key)

    def bw_usage_get(self, context, uuid, start_period, mac):
        return self._manager.bw_usage_update(context, uuid, mac, start_period)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in, bw_out, last_ctr_in, last_ctr_out,
                        last_refreshed=None, update_cells=True):
        return self._manager.bw_usage_update(context, uuid, mac, start_period,
                                             bw_in, bw_out,
                                             last_ctr_in, last_ctr_out,
                                             last_refreshed,
                                             update_cells=update_cells)

    def security_group_get_by_instance(self, context, instance):
        return self._manager.security_group_get_by_instance(context, instance)

    def security_group_rule_get_by_security_group(self, context, secgroup):
        return self._manager.security_group_rule_get_by_security_group(
            context, secgroup)

    def provider_fw_rule_get_all(self, context):
        return self._manager.provider_fw_rule_get_all(context)

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        return self._manager.agent_build_get_by_triple(context, hypervisor,
                                                       os, architecture)

    def block_device_mapping_create(self, context, values):
        return self._manager.block_device_mapping_update_or_create(context,
                                                                   values,
                                                                   create=True)

    def block_device_mapping_update(self, context, bdm_id, values):
        values = dict(values)
        values['id'] = bdm_id
        return self._manager.block_device_mapping_update_or_create(
            context, values, create=False)

    def block_device_mapping_update_or_create(self, context, values):
        return self._manager.block_device_mapping_update_or_create(context,
                                                                   values)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy=True):
        return self._manager.block_device_mapping_get_all_by_instance(
            context, instance, legacy)

    def block_device_mapping_destroy(self, context, bdms):
        return self._manager.block_device_mapping_destroy(context, bdms=bdms)

    def block_device_mapping_destroy_by_instance_and_device(self, context,
                                                            instance,
                                                            device_name):
        return self._manager.block_device_mapping_destroy(
            context, instance=instance, device_name=device_name)

    def block_device_mapping_destroy_by_instance_and_volume(self, context,
                                                            instance,
                                                            volume_id):
        return self._manager.block_device_mapping_destroy(
            context, instance=instance, volume_id=volume_id)

    def vol_get_usage_by_time(self, context, start_time):
        return self._manager.vol_get_usage_by_time(context, start_time)

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        return self._manager.vol_usage_update(context, vol_id,
                                              rd_req, rd_bytes,
                                              wr_req, wr_bytes,
                                              instance, last_refreshed,
                                              update_totals)

    def service_get_all(self, context):
        return self._manager.service_get_all_by(context)

    def service_get_all_by_topic(self, context, topic):
        return self._manager.service_get_all_by(context, topic=topic)

    def service_get_all_by_host(self, context, host):
        return self._manager.service_get_all_by(context, host=host)

    def service_get_by_host_and_topic(self, context, host, topic):
        return self._manager.service_get_all_by(context, topic, host)

    def service_get_by_compute_host(self, context, host):
        result = self._manager.service_get_all_by(context, 'compute', host)
        # FIXME(comstud): A major revision bump to 2.0 should return a
        # single entry, so we should just return 'result' at that point.
        return result[0]

    def service_get_by_args(self, context, host, binary):
        return self._manager.service_get_all_by(context, host=host,
                                                binary=binary)

    def action_event_start(self, context, values):
        return self._manager.action_event_start(context, values)

    def action_event_finish(self, context, values):
        return self._manager.action_event_finish(context, values)

    def service_create(self, context, values):
        return self._manager.service_create(context, values)

    def service_destroy(self, context, service_id):
        return self._manager.service_destroy(context, service_id)

    def compute_node_create(self, context, values):
        return self._manager.compute_node_create(context, values)

    def compute_node_update(self, context, node, values, prune_stats=False):
        return self._manager.compute_node_update(context, node, values,
                                                 prune_stats)

    def compute_node_delete(self, context, node):
        return self._manager.compute_node_delete(context, node)

    def service_update(self, context, service, values):
        return self._manager.service_update(context, service, values)

    def task_log_get(self, context, task_name, begin, end, host, state=None):
        return self._manager.task_log_get(context, task_name, begin, end,
                                          host, state)

    def task_log_begin_task(self, context, task_name, begin, end, host,
                            task_items=None, message=None):
        return self._manager.task_log_begin_task(context, task_name,
                                                 begin, end, host,
                                                 task_items, message)

    def task_log_end_task(self, context, task_name, begin, end, host,
                          errors, message=None):
        return self._manager.task_log_end_task(context, task_name,
                                               begin, end, host,
                                               errors, message)

    def notify_usage_exists(self, context, instance, current_period=False,
                            ignore_missing_network_data=True,
                            system_metadata=None, extra_usage_info=None):
        return self._manager.notify_usage_exists(
            context, instance, current_period, ignore_missing_network_data,
            system_metadata, extra_usage_info)

    def security_groups_trigger_handler(self, context, event, *args):
        return self._manager.security_groups_trigger_handler(context,
                                                             event, args)

    def security_groups_trigger_members_refresh(self, context, group_ids):
        return self._manager.security_groups_trigger_members_refresh(context,
                                                                     group_ids)

    def network_migrate_instance_start(self, context, instance, migration):
        return self._manager.network_migrate_instance_start(context,
                                                            instance,
                                                            migration)

    def network_migrate_instance_finish(self, context, instance, migration):
        return self._manager.network_migrate_instance_finish(context,
                                                             instance,
                                                             migration)

    def quota_commit(self, context, reservations, project_id=None,
                     user_id=None):
        return self._manager.quota_commit(context, reservations,
                                          project_id=project_id,
                                          user_id=user_id)

    def quota_rollback(self, context, reservations, project_id=None,
                       user_id=None):
        return self._manager.quota_rollback(context, reservations,
                                            project_id=project_id,
                                            user_id=user_id)

    def get_ec2_ids(self, context, instance):
        return self._manager.get_ec2_ids(context, instance)

    def compute_confirm_resize(self, context, instance, migration_ref):
        return self._manager.compute_confirm_resize(context, instance,
                                                    migration_ref)

    def compute_unrescue(self, context, instance):
        return self._manager.compute_unrescue(context, instance)


class LocalComputeTaskAPI(object):
    def __init__(self):
        # TODO(danms): This needs to be something more generic for
        # other/future users of this sort of functionality.
        self._manager = utils.ExceptionHelper(
                manager.ComputeTaskManager())

    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
                  flavor, block_migration, disk_over_commit,
                  reservations=None):
        self._manager.migrate_server(
            context, instance, scheduler_hint, live, rebuild, flavor,
            block_migration, disk_over_commit, reservations)

    def build_instances(self, context, instances, image,
            filter_properties, admin_password, injected_files,
            requested_networks, security_groups, block_device_mapping,
            legacy_bdm=True):
        utils.spawn_n(self._manager.build_instances, context,
                instances=instances, image=image,
                filter_properties=filter_properties,
                admin_password=admin_password, injected_files=injected_files,
                requested_networks=requested_networks,
                security_groups=security_groups,
                block_device_mapping=block_device_mapping,
                legacy_bdm=legacy_bdm)

    def unshelve_instance(self, context, instance):
        utils.spawn_n(self._manager.unshelve_instance, context,
                instance=instance)


class API(LocalAPI):
    """Conductor API that does updates via RPC to the ConductorManager."""

    def __init__(self):
        self._manager = rpcapi.ConductorAPI()
        self.base_rpcapi = baserpc.BaseAPI(topic=CONF.conductor.topic)

    def wait_until_ready(self, context, early_timeout=10, early_attempts=10):
        '''Wait until a conductor service is up and running.

        This method calls the remote ping() method on the conductor topic until
        it gets a response.  It starts with a shorter timeout in the loop
        (early_timeout) up to early_attempts number of tries.  It then drops
        back to the globally configured timeout for rpc calls for each retry.
        '''
        attempt = 0
        timeout = early_timeout
        while True:
            # NOTE(danms): Try ten times with a short timeout, and then punt
            # to the configured RPC timeout after that
            if attempt == early_attempts:
                timeout = None
            attempt += 1

            # NOTE(russellb): This is running during service startup. If we
            # allow an exception to be raised, the service will shut down.
            # This may fail the first time around if nova-conductor wasn't
            # running when this service started.
            try:
                self.base_rpcapi.ping(context, '1.21 GigaWatts',
                                      timeout=timeout)
                break
            except rpc_common.Timeout:
                LOG.warning(_('Timed out waiting for nova-conductor. '
                                'Is it running? Or did this service start '
                                'before nova-conductor?'))

    def instance_update(self, context, instance_uuid, **updates):
        """Perform an instance update in the database."""
        return self._manager.instance_update(context, instance_uuid,
                                             updates, 'conductor')


class ComputeTaskAPI(object):
    """ComputeTask API that queues up compute tasks for nova-conductor."""

    def __init__(self):
        self.conductor_compute_rpcapi = rpcapi.ComputeTaskAPI()

    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
                  flavor, block_migration, disk_over_commit,
                  reservations=None):
        self.conductor_compute_rpcapi.migrate_server(
            context, instance, scheduler_hint, live, rebuild,
            flavor, block_migration, disk_over_commit, reservations)

    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping, legacy_bdm=True):
        self.conductor_compute_rpcapi.build_instances(context,
                instances=instances, image=image,
                filter_properties=filter_properties,
                admin_password=admin_password, injected_files=injected_files,
                requested_networks=requested_networks,
                security_groups=security_groups,
                block_device_mapping=block_device_mapping,
                legacy_bdm=legacy_bdm)

    def unshelve_instance(self, context, instance):
        self.conductor_compute_rpcapi.unshelve_instance(context,
                instance=instance)
