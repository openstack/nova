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

from oslo_log import log as logging
import oslo_messaging as messaging

from nova import baserpc
from nova.conductor import rpcapi
import nova.conf
from nova.image import glance

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class API(object):
    """Conductor API that does updates via RPC to the ConductorManager."""

    def __init__(self):
        self.conductor_rpcapi = rpcapi.ConductorAPI()
        self.base_rpcapi = baserpc.BaseAPI(topic=rpcapi.RPC_TOPIC)

    def object_backport_versions(self, context, objinst, object_versions):
        return self.conductor_rpcapi.object_backport_versions(context, objinst,
                                                              object_versions)

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
                    LOG.info('nova-conductor connection '
                             'established successfully')
                break
            except messaging.MessagingTimeout:
                has_timedout = True
                LOG.warning('Timed out waiting for nova-conductor.  '
                            'Is it running? Or did this service start '
                            'before nova-conductor?  '
                            'Reattempting establishment of '
                            'nova-conductor connection...')


class ComputeTaskAPI(object):
    """ComputeTask API that queues up compute tasks for nova-conductor."""

    def __init__(self):
        self.conductor_compute_rpcapi = rpcapi.ComputeTaskAPI()
        self.image_api = glance.API()

    # TODO(stephenfin): Remove the 'reservations' parameter since we don't use
    # reservations anymore
    def resize_instance(self, context, instance, scheduler_hint, flavor,
                        reservations=None, clean_shutdown=True,
                        request_spec=None, host_list=None, do_cast=False):
        self.conductor_compute_rpcapi.migrate_server(
            context, instance, scheduler_hint, live=False, rebuild=False,
            flavor=flavor, block_migration=None, disk_over_commit=None,
            reservations=reservations, clean_shutdown=clean_shutdown,
            request_spec=request_spec, host_list=host_list,
            do_cast=do_cast)

    def live_migrate_instance(self, context, instance, host_name,
                              block_migration, disk_over_commit,
                              request_spec=None, async_=False):
        scheduler_hint = {'host': host_name}
        if async_:
            self.conductor_compute_rpcapi.live_migrate_instance(
                context, instance, scheduler_hint, block_migration,
                disk_over_commit, request_spec)
        else:
            self.conductor_compute_rpcapi.migrate_server(
                context, instance, scheduler_hint, True, False, None,
                block_migration, disk_over_commit, None,
                request_spec=request_spec)

    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping, legacy_bdm=True,
            request_spec=None, host_lists=None):
        self.conductor_compute_rpcapi.build_instances(context,
                instances=instances, image=image,
                filter_properties=filter_properties,
                admin_password=admin_password, injected_files=injected_files,
                requested_networks=requested_networks,
                security_groups=security_groups,
                block_device_mapping=block_device_mapping,
                legacy_bdm=legacy_bdm, request_spec=request_spec,
                host_lists=host_lists)

    def schedule_and_build_instances(self, context, build_requests,
                                     request_spec, image,
                                     admin_password, injected_files,
                                     requested_networks, block_device_mapping,
                                     tags=None):
        self.conductor_compute_rpcapi.schedule_and_build_instances(
            context, build_requests, request_spec, image,
            admin_password, injected_files, requested_networks,
            block_device_mapping, tags)

    def unshelve_instance(self, context, instance, request_spec=None):
        self.conductor_compute_rpcapi.unshelve_instance(context,
                instance=instance, request_spec=request_spec)

    def rebuild_instance(self, context, instance, orig_image_ref, image_ref,
                         injected_files, new_pass, orig_sys_metadata,
                         bdms, recreate=False, on_shared_storage=False,
                         preserve_ephemeral=False, host=None,
                         request_spec=None):
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
                host=host,
                request_spec=request_spec)

    def cache_images(self, context, aggregate, image_ids):
        """Request images be pre-cached on hosts within an aggregate.

        :param context: The RequestContext
        :param aggregate: The objects.Aggregate representing the hosts to
                          contact
        :param image_ids: A list of image ID strings to send to the hosts
        """
        for image_id in image_ids:
            # Validate that we can get the image by id before we go
            # ask a bunch of hosts to do the same. We let this bubble
            # up to the API, which catches NovaException for the 4xx and
            # otherwise 500s if this fails in some unexpected way.
            self.image_api.get(context, image_id)
        self.conductor_compute_rpcapi.cache_images(context, aggregate,
                                                   image_ids)

    def confirm_snapshot_based_resize(
            self, ctxt, instance, migration, do_cast=True):
        self.conductor_compute_rpcapi.confirm_snapshot_based_resize(
            ctxt, instance, migration, do_cast=do_cast)

    def revert_snapshot_based_resize(
            self, ctxt, instance, migration):
        self.conductor_compute_rpcapi.revert_snapshot_based_resize(
            ctxt, instance, migration)
