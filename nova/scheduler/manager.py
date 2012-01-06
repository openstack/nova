# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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
from nova import log as logging
from nova import manager
from nova import rpc
from nova.scheduler import zone_manager
from nova import utils

LOG = logging.getLogger('nova.scheduler.manager')
FLAGS = flags.FLAGS
flags.DEFINE_string('scheduler_driver',
                    'nova.scheduler.multi.MultiScheduler',
                    'Default driver to use for the scheduler')


class SchedulerManager(manager.Manager):
    """Chooses a host to run instances on."""

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        self.zone_manager = zone_manager.ZoneManager()
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = utils.import_object(scheduler_driver)
        self.driver.set_zone_manager(self.zone_manager)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def __getattr__(self, key):
        """Converts all method calls to use the schedule method"""
        return functools.partial(self._schedule, key)

    @manager.periodic_task
    def _poll_child_zones(self, context):
        """Poll child zones periodically to get status."""
        self.zone_manager.ping(context)

    def get_host_list(self, context=None):
        """Get a list of hosts from the ZoneManager."""
        return self.zone_manager.get_host_list()

    def get_zone_list(self, context=None):
        """Get a list of zones from the ZoneManager."""
        return self.zone_manager.get_zone_list()

    def get_zone_capabilities(self, context=None):
        """Get the normalized set of capabilities for this zone."""
        return self.zone_manager.get_zone_capabilities(context)

    def update_service_capabilities(self, context=None, service_name=None,
                                                host=None, capabilities=None):
        """Process a capability update from a service node."""
        if not capabilities:
            capabilities = {}
        self.zone_manager.update_service_capabilities(service_name,
                            host, capabilities)

    def select(self, context=None, *args, **kwargs):
        """Select a list of hosts best matching the provided specs."""
        return self.driver.select(context, *args, **kwargs)

    def _schedule(self, method, context, topic, *args, **kwargs):
        """Tries to call schedule_* method on the driver to retrieve host.

        Falls back to schedule(context, topic) if method doesn't exist.
        """
        driver_method = 'schedule_%s' % method
        try:
            real_meth = getattr(self.driver, driver_method)
            args = (context,) + args
        except AttributeError, e:
            LOG.warning(_("Driver Method %(driver_method)s missing: %(e)s."
                          "Reverting to schedule()") % locals())
            real_meth = self.driver.schedule
            args = (context, topic, method) + args

        # Scheduler methods are responsible for casting.
        try:
            return real_meth(*args, **kwargs)
        except exception.NoValidHost as ex:
            self._set_instance_error(method, context, ex, *args, **kwargs)
        except Exception as ex:
            with utils.save_and_reraise_exception():
                self._set_instance_error(method, context, ex, *args, **kwargs)

    # NOTE (David Subiros) : If the exception is raised during run_instance
    #                        method, we may or may not have an instance_id
    def _set_instance_error(self, method, context, ex, *args, **kwargs):
        """Sets VM to Error state"""
        LOG.warning(_("Failed to schedule_%(method)s: %(ex)s") % locals())
        if method != "start_instance" and method != "run_instance":
            return
        # FIXME(comstud): Clean this up after fully on UUIDs.
        instance_id = kwargs.get('instance_uuid', kwargs.get('instance_id'))
        if not instance_id:
            # FIXME(comstud): We should make this easier.  run_instance
            # only sends a request_spec, and an instance may or may not
            # have been created in the API (or scheduler) already.  If it
            # was created, there's a 'uuid' set in the instance_properties
            # of the request_spec.
            request_spec = kwargs.get('request_spec', {})
            properties = request_spec.get('instance_properties', {})
            instance_id = properties.get('uuid', {})
        if instance_id:
            LOG.warning(_("Setting instance %(instance_id)s to "
                    "ERROR state.") % locals())
            db.instance_update(context, instance_id,
                    {'vm_state': vm_states.ERROR})

    # NOTE (masumotok) : This method should be moved to nova.api.ec2.admin.
    #                    Based on bexar design summit discussion,
    #                    just put this here for bexar release.
    def show_host_resources(self, context, host):
        """Shows the physical/usage resource given by hosts.

        :param context: security context
        :param host: hostname
        :returns:
            example format is below.
            {'resource':D, 'usage':{proj_id1:D, proj_id2:D}}
            D: {'vcpus': 3, 'memory_mb': 2048, 'local_gb': 2048,
                'vcpus_used': 12, 'memory_mb_used': 10240,
                'local_gb_used': 64}

        """
        # Update latest compute_node table
        topic = db.queue_get_for(context, FLAGS.compute_topic, host)
        rpc.call(context, topic, {"method": "update_available_resource"})

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
            vcpus = [i['vcpus'] for i in instance_refs \
                if i['project_id'] == project_id]

            mem = [i['memory_mb']  for i in instance_refs \
                if i['project_id'] == project_id]

            disk = [i['local_gb']  for i in instance_refs \
                if i['project_id'] == project_id]

            usage[project_id] = {'vcpus': reduce(lambda x, y: x + y, vcpus),
                                 'memory_mb': reduce(lambda x, y: x + y, mem),
                                 'local_gb': reduce(lambda x, y: x + y, disk)}

        return {'resource': resource, 'usage': usage}
