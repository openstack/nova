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

from oslo_config import cfg
import oslo_messaging as messaging

from nova import baserpc
from nova.conductor import manager
from nova.conductor import rpcapi
from nova.i18n import _LI, _LW
from nova.openstack.common import log as logging
from nova import utils

conductor_opts = [
    cfg.BoolOpt('use_local',
                default=False,
                help='Perform nova-conductor operations locally'),
    cfg.StrOpt('topic',
               default='conductor',
               help='The topic on which conductor nodes listen'),
    cfg.StrOpt('manager',
               default='nova.conductor.manager.ConductorManager',
               help='Full class name for the Manager for conductor'),
    cfg.IntOpt('workers',
               help='Number of workers for OpenStack Conductor service. '
                    'The default will be the number of CPUs available.')
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

    def instance_get_all_by_host(self, context, host, columns_to_join=None):
        return self._manager.instance_get_all_by_host(
            context, host, None, columns_to_join=columns_to_join)

    def instance_get_all_by_host_and_node(self, context, host, node):
        return self._manager.instance_get_all_by_host(context, host, node,
                None)

    def migration_get_in_progress_by_host_and_node(self, context, host, node):
        return self._manager.migration_get_in_progress_by_host_and_node(
            context, host, node)

    def aggregate_metadata_get_by_host(self, context, host,
                                       key='availability_zone'):
        return self._manager.aggregate_metadata_get_by_host(context,
                                                            host,
                                                            key)

    def bw_usage_get(self, context, uuid, start_period, mac):
        return self._manager.bw_usage_update(context, uuid, mac, start_period,
                None, None, None, None, None, False)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in, bw_out, last_ctr_in, last_ctr_out,
                        last_refreshed=None, update_cells=True):
        return self._manager.bw_usage_update(context, uuid, mac, start_period,
                                             bw_in, bw_out,
                                             last_ctr_in, last_ctr_out,
                                             last_refreshed,
                                             update_cells=update_cells)

    def provider_fw_rule_get_all(self, context):
        return self._manager.provider_fw_rule_get_all(context)

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
                                                                   values,
                                                                   create=None)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy=True):
        return self._manager.block_device_mapping_get_all_by_instance(
            context, instance, legacy)

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
        return self._manager.service_get_all_by(context, host=None, topic=None,
                binary=None)

    def service_get_all_by_topic(self, context, topic):
        return self._manager.service_get_all_by(context, topic=topic,
                host=None, binary=None)

    def service_get_all_by_host(self, context, host):
        return self._manager.service_get_all_by(context, host=host, topic=None,
                binary=None)

    def service_get_by_host_and_topic(self, context, host, topic):
        return self._manager.service_get_all_by(context, topic, host,
                binary=None)

    def service_get_by_compute_host(self, context, host):
        result = self._manager.service_get_all_by(context, 'compute', host,
                binary=None)
        # FIXME(comstud): A major revision bump to 2.0 should return a
        # single entry, so we should just return 'result' at that point.
        return result[0]

    def service_get_by_args(self, context, host, binary):
        return self._manager.service_get_all_by(context, host=host,
                                                binary=binary, topic=None)

    def service_create(self, context, values):
        return self._manager.service_create(context, values)

    def service_destroy(self, context, service_id):
        return self._manager.service_destroy(context, service_id)

    def compute_node_create(self, context, values):
        return self._manager.compute_node_create(context, values)

    def compute_node_update(self, context, node, values, prune_stats=False):
        # NOTE(belliott) ignore prune_stats param, it's no longer relevant
        return self._manager.compute_node_update(context, node, values)

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

    def get_ec2_ids(self, context, instance):
        return self._manager.get_ec2_ids(context, instance)

    def object_backport(self, context, objinst, target_version):
        return self._manager.object_backport(context, objinst, target_version)


class LocalComputeTaskAPI(object):
    def __init__(self):
        # TODO(danms): This needs to be something more generic for
        # other/future users of this sort of functionality.
        self._manager = utils.ExceptionHelper(
                manager.ComputeTaskManager())

    def resize_instance(self, context, instance, extra_instance_updates,
                        scheduler_hint, flavor, reservations,
                        clean_shutdown=True):
        # NOTE(comstud): 'extra_instance_updates' is not used here but is
        # needed for compatibility with the cells_rpcapi version of this
        # method.
        self._manager.migrate_server(
            context, instance, scheduler_hint, live=False, rebuild=False,
            flavor=flavor, block_migration=None, disk_over_commit=None,
            reservations=reservations, clean_shutdown=clean_shutdown)

    def live_migrate_instance(self, context, instance, host_name,
                              block_migration, disk_over_commit):
        scheduler_hint = {'host': host_name}
        self._manager.migrate_server(
            context, instance, scheduler_hint, True, False, None,
            block_migration, disk_over_commit, None)

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

    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate=False, on_shared_storage=False,
                         preserve_ephemeral=False, host=None, kwargs=None):
        # kwargs unused but required for cell compatibility.
        utils.spawn_n(self._manager.rebuild_instance, context,
                instance=instance,
                new_pass=new_pass,
                injected_files=injected_files,
                image_ref=image_ref,
                orig_image_ref=orig_image_ref,
                orig_sys_metadata=orig_sys_metadata,
                bdms=bdms,
                recreate=recreate,
                on_shared_storage=on_shared_storage,
                host=host,
                preserve_ephemeral=preserve_ephemeral)


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
        # if we show the timeout message, make sure we show a similar
        # message saying that everything is now working to avoid
        # confusion
        has_timedout = False
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
                if has_timedout:
                    LOG.info(_LI('nova-conductor connection '
                                 'established successfully'))
                break
            except messaging.MessagingTimeout:
                has_timedout = True
                LOG.warning(_LW('Timed out waiting for nova-conductor.  '
                                'Is it running? Or did this service start '
                                'before nova-conductor?  '
                                'Reattempting establishment of '
                                'nova-conductor connection...'))

    def instance_update(self, context, instance_uuid, **updates):
        """Perform an instance update in the database."""
        return self._manager.instance_update(context, instance_uuid,
                                             updates, 'conductor')


class ComputeTaskAPI(object):
    """ComputeTask API that queues up compute tasks for nova-conductor."""

    def __init__(self):
        self.conductor_compute_rpcapi = rpcapi.ComputeTaskAPI()

    def resize_instance(self, context, instance, extra_instance_updates,
                        scheduler_hint, flavor, reservations,
                        clean_shutdown=True):
        # NOTE(comstud): 'extra_instance_updates' is not used here but is
        # needed for compatibility with the cells_rpcapi version of this
        # method.
        self.conductor_compute_rpcapi.migrate_server(
            context, instance, scheduler_hint, live=False, rebuild=False,
            flavor=flavor, block_migration=None, disk_over_commit=None,
            reservations=reservations, clean_shutdown=clean_shutdown)

    def live_migrate_instance(self, context, instance, host_name,
                              block_migration, disk_over_commit):
        scheduler_hint = {'host': host_name}
        self.conductor_compute_rpcapi.migrate_server(
            context, instance, scheduler_hint, True, False, None,
            block_migration, disk_over_commit, None)

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

    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate=False, on_shared_storage=False,
                         preserve_ephemeral=False, host=None, kwargs=None):
        # kwargs unused but required for cell compatibility
        self.conductor_compute_rpcapi.rebuild_instance(context,
                instance=instance,
                new_pass=new_pass,
                injected_files=injected_files,
                image_ref=image_ref,
                orig_image_ref=orig_image_ref,
                orig_sys_metadata=orig_sys_metadata,
                bdms=bdms,
                recreate=recreate,
                on_shared_storage=on_shared_storage,
                preserve_ephemeral=preserve_ephemeral,
                host=host)
