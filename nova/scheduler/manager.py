# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack, LLC.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

"""
Scheduler Service
"""

import functools

from nova.compute import vm_states
from nova import db
from nova import exception
from nova import flags
from nova import manager
from nova import notifications
from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common.rpc import common as rpc_common
from nova import quota


LOG = logging.getLogger(__name__)

scheduler_driver_opt = cfg.StrOpt('scheduler_driver',
        default='nova.scheduler.multi.MultiScheduler',
        help='Default driver to use for the scheduler')

FLAGS = flags.FLAGS
FLAGS.register_opt(scheduler_driver_opt)

QUOTAS = quota.QUOTAS


class SchedulerManager(manager.Manager):
    """Chooses a host to run instances on."""

    RPC_API_VERSION = '1.2'

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def __getattr__(self, key):
        """Converts all method calls to use the schedule method"""
        # NOTE(russellb) Because of what this is doing, we must be careful
        # when changing the API of the scheduler drivers, as that changes
        # the rpc API as well, and the version should be updated accordingly.
        return functools.partial(self._schedule, key)

    def get_host_list(self, context):
        """Get a list of hosts from the HostManager.

        Currently unused, but left for backwards compatibility.
        """
        raise rpc_common.RPCException(message=_('Deprecated in version 1.0'))

    def get_service_capabilities(self, context):
        """Get the normalized set of capabilities for this zone.

        Has been unused since pre-essex, but remains for rpc API 1.X
        completeness.
        """
        raise rpc_common.RPCException(message=_('Deprecated in version 1.0'))

    def update_service_capabilities(self, context, service_name=None,
            host=None, capabilities=None, **kwargs):
        """Process a capability update from a service node."""
        if capabilities is None:
            capabilities = {}
        self.driver.update_service_capabilities(service_name, host,
                capabilities)

    def _schedule(self, method, context, topic, *args, **kwargs):
        """Tries to call schedule_* method on the driver to retrieve host.
        Falls back to schedule(context, topic) if method doesn't exist.
        """
        driver_method_name = 'schedule_%s' % method
        try:
            driver_method = getattr(self.driver, driver_method_name)
            args = (context,) + args
        except AttributeError, e:
            LOG.warning(_("Driver Method %(driver_method_name)s missing: "
                       "%(e)s. Reverting to schedule()") % locals())
            driver_method = self.driver.schedule
            args = (context, topic, method) + args

        # Scheduler methods are responsible for casting.
        try:
            return driver_method(*args, **kwargs)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                request_spec = kwargs.get('request_spec', {})
                self._set_vm_state_and_notify(method,
                                             {'vm_state': vm_states.ERROR},
                                             context, ex, request_spec)

    def run_instance(self, context, request_spec, admin_password,
            injected_files, requested_networks, is_first_time,
            filter_properties, reservations, topic=None):
        """Tries to call schedule_run_instance on the driver.
        Sets instance vm_state to ERROR on exceptions
        """
        try:
            result = self.driver.schedule_run_instance(context,
                    request_spec, admin_password, injected_files,
                    requested_networks, is_first_time, filter_properties,
                    reservations)
            return result
        except exception.NoValidHost as ex:
            # don't reraise
            self._set_vm_state_and_notify('run_instance',
                                         {'vm_state': vm_states.ERROR},
                                          context, ex, request_spec)
            if reservations:
                QUOTAS.rollback(context, reservations)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                self._set_vm_state_and_notify('run_instance',
                                             {'vm_state': vm_states.ERROR},
                                             context, ex, request_spec)
                if reservations:
                    QUOTAS.rollback(context, reservations)

    def prep_resize(self, context, image, update_db, request_spec,
                    filter_properties, instance=None, instance_uuid=None,
                    instance_type=None, instance_type_id=None, topic=None):
        """Tries to call schedule_prep_resize on the driver.
        Sets instance vm_state to ACTIVE on NoHostFound
        Sets vm_state to ERROR on other exceptions
        """
        if not instance:
            instance = db.instance_get_by_uuid(context, instance_uuid)

        if not instance_type:
            instance_type = db.instance_type_get(context, instance_type_id)

        try:
            kwargs = {
                'context': context,
                'image': image,
                'update_db': update_db,
                'request_spec': request_spec,
                'filter_properties': filter_properties,
                'instance': instance,
                'instance_type': instance_type,
            }
            return self.driver.schedule_prep_resize(**kwargs)
        except exception.NoValidHost as ex:
            self._set_vm_state_and_notify('prep_resize',
                                         {'vm_state': vm_states.ACTIVE,
                                          'task_state': None},
                                         context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                self._set_vm_state_and_notify('prep_resize',
                                             {'vm_state': vm_states.ERROR},
                                             context, ex, request_spec)

    def _set_vm_state_and_notify(self, method, updates, context, ex,
                                 request_spec):
        """changes VM state and notifies"""
        # FIXME(comstud): Re-factor this somehow. Not sure this belongs in the
        # scheduler manager like this. We should make this easier.
        # run_instance only sends a request_spec, and an instance may or may
        # not have been created in the API (or scheduler) already. If it was
        # created, there's a 'uuid' set in the instance_properties of the
        # request_spec.
        # (littleidea): I refactored this a bit, and I agree
        # it should be easier :)
        # The refactoring could go further but trying to minimize changes
        # for essex timeframe

        LOG.warning(_("Failed to schedule_%(method)s: %(ex)s") % locals())

        vm_state = updates['vm_state']
        properties = request_spec.get('instance_properties', {})
        instance_uuid = properties.get('uuid', {})

        if instance_uuid:
            state = vm_state.upper()
            LOG.warning(_('Setting instance to %(state)s state.'), locals(),
                        instance_uuid=instance_uuid)

            # update instance state and notify on the transition
            (old_ref, new_ref) = db.instance_update_and_get_original(context,
                    instance_uuid, updates)
            notifications.send_update(context, old_ref, new_ref,
                    service="scheduler")

        payload = dict(request_spec=request_spec,
                       instance_properties=properties,
                       instance_id=instance_uuid,
                       state=vm_state,
                       method=method,
                       reason=ex)

        notifier.notify(context, notifier.publisher_id("scheduler"),
                        'scheduler.' + method, notifier.ERROR, payload)

    # NOTE (masumotok) : This method should be moved to nova.api.ec2.admin.
    # Based on bexar design summit discussion,
    # just put this here for bexar release.
    def show_host_resources(self, context, host):
        """Shows the physical/usage resource given by hosts.

        :param context: security context
        :param host: hostname
        :returns:
            example format is below::

                {'resource':D, 'usage':{proj_id1:D, proj_id2:D}}
                D: {'vcpus': 3, 'memory_mb': 2048, 'local_gb': 2048,
                    'vcpus_used': 12, 'memory_mb_used': 10240,
                    'local_gb_used': 64}

        """
        # Getting compute node info and related instances info
        compute_ref = db.service_get_all_compute_by_host(context, host)
        compute_ref = compute_ref[0]
        instance_refs = db.instance_get_all_by_host(context,
                                                    compute_ref['host'])

        # Getting total available/used resource
        compute_ref = compute_ref['compute_node'][0]
        resource = {'vcpus': compute_ref['vcpus'],
                    'memory_mb': compute_ref['memory_mb'],
                    'local_gb': compute_ref['local_gb'],
                    'vcpus_used': compute_ref['vcpus_used'],
                    'memory_mb_used': compute_ref['memory_mb_used'],
                    'local_gb_used': compute_ref['local_gb_used']}
        usage = dict()
        if not instance_refs:
            return {'resource': resource, 'usage': usage}

        # Getting usage resource per project
        project_ids = [i['project_id'] for i in instance_refs]
        project_ids = list(set(project_ids))
        for project_id in project_ids:
            vcpus = [i['vcpus'] for i in instance_refs
                     if i['project_id'] == project_id]

            mem = [i['memory_mb'] for i in instance_refs
                   if i['project_id'] == project_id]

            root = [i['root_gb'] for i in instance_refs
                    if i['project_id'] == project_id]

            ephemeral = [i['ephemeral_gb'] for i in instance_refs
                         if i['project_id'] == project_id]

            usage[project_id] = {'vcpus': sum(vcpus),
                                 'memory_mb': sum(mem),
                                 'root_gb': sum(root),
                                 'ephemeral_gb': sum(ephemeral)}

        return {'resource': resource, 'usage': usage}

    @manager.periodic_task
    def _expire_reservations(self, context):
        QUOTAS.expire(context)
