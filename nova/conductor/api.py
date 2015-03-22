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
from oslo_log import log as logging
import oslo_messaging as messaging

from nova import baserpc
from nova.conductor import manager
from nova.conductor import rpcapi
from nova.i18n import _LI, _LW
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

    def provider_fw_rule_get_all(self, context):
        return self._manager.provider_fw_rule_get_all(context)

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        return self._manager.vol_usage_update(context, vol_id,
                                              rd_req, rd_bytes,
                                              wr_req, wr_bytes,
                                              instance, last_refreshed,
                                              update_totals)

    def compute_node_create(self, context, values):
        return self._manager.compute_node_create(context, values)

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

    def security_groups_trigger_members_refresh(self, context, group_ids):
        return self._manager.security_groups_trigger_members_refresh(context,
                                                                     group_ids)

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
