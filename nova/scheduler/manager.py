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

import logging
import functools

from nova import db
from nova import flags
from nova import manager
from nova import rpc
from nova import utils
from nova import exception
from nova.api.ec2 import cloud
from nova.compute import power_state

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
        logging.debug("Casting to %s %s for %s", topic, host, method)

    def live_migration(self, context, ec2_id, dest):
        """ live migration method"""

        # (masumotok) below pre-checking is followed by 
        # http://wiki.libvirt.org/page/TodoPreMigrationChecks

        # 1. get instance id
        internal_id = cloud.ec2_id_to_internal_id(ec2_id)
        instance_ref = db.instance_get_by_internal_id(context, internal_id)
        instance_id = instance_ref['id']

        # 2. get src host and dst host
        src = instance_ref['launched_on']
        shost_ref = db.host_get_by_name(context, src )
        dhost_ref = db.host_get_by_name(context, dest)

        # 3. dest should be compute
        services = db.service_get_all_by_topic(context, 'compute')
        logging.warn('%s' % [service.host for service in services])
        if dest not in [service.host for service in services] :
            raise exception.Invalid('%s must be compute node' % dest)

        # 4. check hypervisor is same
        shypervisor = shost_ref['hypervisor_type'] 
        dhypervisor = dhost_ref['hypervisor_type']
        if shypervisor != dhypervisor:
            msg = 'Different hypervisor type(%s->%s)' % (shypervisor, dhypervisor)
            raise exception.Invalid(msg)
        
        # 5. check hypervisor version 
        shypervisor = shost_ref['hypervisor_version'] 
        dhypervisor = dhost_ref['hypervisor_version']
        if shypervisor > dhypervisor:
            msg = 'Older hypervisor version(%s->%s)' % (shypervisor, dhypervisor)
            raise exception.Invalid(msg)

        # 6. check cpuinfo
        cpuinfo = shost_ref['cpu_info']
        if str != type(cpuinfo): 
            msg = 'Unexpected err: no cpu_info for %s found on DB.hosts' % src
            raise exception.Invalid(msg)

        logging.warn('cpuinfo %s %d' % (cpuinfo, len(cpuinfo)))
        ret = rpc.call(context,
                       db.queue_get_for(context, FLAGS.compute_topic, dest),
                       {"method": 'compareCPU',
                        "args": {'xml': cpuinfo}})

        if int != type(ret): 
            raise ret

        if 0 >= ret :
            msg = '%s doesnt have compatibility to %s(where %s launching at)\n' \
                % (dest, src, ec2_id)
            msg += 'result:%d \n' % ret
            msg += 'Refer to %s'  % \
                'http://libvirt.org/html/libvirt-libvirt.html#virCPUCompareResult'
            raise exception.Invalid(msg)

        # 7. check dst host still has enough capacities
        self.has_enough_resource(context, instance_id, dest)

        # 8. change instance_state
        db.instance_set_state(context,
                              instance_id,
                              power_state.PAUSED,
                              'migrating')

        # 9. request live migration
        host = instance_ref['host']
        rpc.cast(context,
                 db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": 'live_migration',
                  "args": {'instance_id': instance_id,
                             'dest': dest}})


    def has_enough_resource(self, context, instance_id, dest):
        """ check if destination host has enough resource for live migration"""

        # get instance information
        instance_ref = db.instance_get(context, instance_id)
        ec2_id = instance_ref['hostname']
        vcpus = instance_ref['vcpus']
        mem = instance_ref['memory_mb']
        hdd = instance_ref['local_gb']

        # get host information
        host_ref = db.host_get_by_name(context, dest)
        total_cpu = int(host_ref['vcpus'])
        total_mem = int(host_ref['memory_mb'])
        total_hdd = int(host_ref['local_gb'])

        instances_ref = db.instance_get_all_by_host(context, dest)
        for i_ref in instances_ref:
            total_cpu -= int(i_ref['vcpus'])
            total_mem -= int(i_ref['memory_mb'])
            total_hdd -= int(i_ref['local_gb'])

        # check host has enough information
        logging.debug('host(%s) remains vcpu:%s mem:%s hdd:%s,' %
                      (dest, total_cpu, total_mem, total_hdd))
        logging.debug('instance(%s) has vcpu:%s mem:%s hdd:%s,' %
                      (ec2_id, total_cpu, total_mem, total_hdd))

        if total_cpu <= vcpus or total_mem <= mem or total_hdd <= hdd:
            msg = '%s doesnt have enough resource for %s' % (dest, ec2_id)
            raise exception.NotEmpty(msg)

        logging.debug('%s has enough resource for %s' % (dest, ec2_id))

    def show_host_resource(self, context, host, *args):
        """ show the physical/usage resource given by hosts."""

        try:
            host_ref = db.host_get_by_name(context, host)
        except exception.NotFound:
            return {'ret': False, 'msg': 'No such Host'}
        except:
            raise

        # get physical resource information
        h_resource = {'vcpus': host_ref['vcpus'],
                     'memory_mb': host_ref['memory_mb'],
                     'local_gb': host_ref['local_gb']}

        # get usage resource information
        u_resource = {}
        instances_ref = db.instance_get_all_by_host(context, host_ref['name'])

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
