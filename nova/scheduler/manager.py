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

from nova import db
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils
from nova import exception

LOG = logging.getLogger('nova.scheduler.manager')
FLAGS = flags.FLAGS
flags.DEFINE_string('scheduler_driver',
                    'nova.scheduler.chance.ChanceScheduler',
                    'Driver to use for the scheduler')


class SchedulerManager(manager.Manager):
    """Chooses a host to run instances on."""
    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = utils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def __getattr__(self, key):
        """Converts all method calls to use the schedule method"""
        return functools.partial(self._schedule, key)

    def _schedule(self, method, context, topic, *args, **kwargs):
        """Tries to call schedule_* method on the driver to retrieve host.

        Falls back to schedule(context, topic) if method doesn't exist.
        """
        driver_method = 'schedule_%s' % method
        elevated = context.elevated()
        try:
            host = getattr(self.driver, driver_method)(elevated, *args,
                                                       **kwargs)
        except AttributeError:
            host = self.driver.schedule(elevated, topic, *args, **kwargs)

        rpc.cast(context,
                 db.queue_get_for(context, topic, host),
                 {"method": method,
                  "args": kwargs})
        LOG.debug(_("Casting to %s %s for %s"), topic, host, method)

    # NOTE (masumotok) : This method should be moved to nova.api.ec2.admin.
    #                    Based on bear design summit discussion,
    #                    just put this here for bexar release.
    def show_host_resource(self, context, host, *args):
        """ show the physical/usage resource given by hosts."""

        services = db.service_get_all_by_host(context, host)
        if len(services) == 0:
            return {'ret': False, 'msg': 'No such Host'}

        compute = [ s for s in services if s['topic'] == 'compute']
        if 0 == len(compute): 
            service_ref = services[0]
        else:
            service_ref = compute[0]

        # Getting physical resource information
        h_resource = {'vcpus': service_ref['vcpus'],
                     'memory_mb': service_ref['memory_mb'],
                     'local_gb': service_ref['local_gb']}

        
        # Getting usage resource information
        u_resource = {}
        instances_ref = db.instance_get_all_by_host(context, 
                                                    service_ref['host'])

        if 0 == len(instances_ref):
            return {'ret': True, 'phy_resource': h_resource, 'usage': {}}

        project_ids = [i['project_id'] for i in instances_ref]
        project_ids = list(set(project_ids))
        for p_id in project_ids:
            vcpus = db.instance_get_vcpu_sum_by_host_and_project(context,
                                                                 host,
                                                                 p_id)
            mem = db.instance_get_memory_sum_by_host_and_project(context,
                                                                 host,
                                                                 p_id)
            hdd = db.instance_get_disk_sum_by_host_and_project(context,
                                                               host,
                                                               p_id)
            u_resource[p_id] = {'vcpus': vcpus,
                                'memory_mb': mem,
                                'local_gb': hdd}

        return {'ret': True, 'phy_resource': h_resource, 'usage': u_resource}
