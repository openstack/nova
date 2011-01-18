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
Scheduler base class that all Schedulers should inherit from
"""

import datetime

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova.compute import power_state

FLAGS = flags.FLAGS
flags.DEFINE_integer('service_down_time', 60,
                     'maximum time since last checkin for up service')


class NoValidHost(exception.Error):
    """There is no valid host for the command."""
    pass


class WillNotSchedule(exception.Error):
    """The specified host is not up or doesn't exist."""
    pass


class Scheduler(object):
    """The base class that all Scheduler clases should inherit from."""

    @staticmethod
    def service_is_up(service):
        """Check whether a service is up based on last heartbeat."""
        last_heartbeat = service['updated_at'] or service['created_at']
        # Timestamps in DB are UTC.
        elapsed = datetime.datetime.utcnow() - last_heartbeat
        return elapsed < datetime.timedelta(seconds=FLAGS.service_down_time)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service.host
                for service in services
                if self.service_is_up(service)]

    def schedule(self, context, topic, *_args, **_kwargs):
        """Must override at least this method for scheduler to work."""
        raise NotImplementedError(_("Must implement a fallback schedule"))

    def schedule_live_migration(self, context, instance_id, dest):
        """ live migration method """

        # Whether instance exists and running
        instance_ref = db.instance_get(context, instance_id)
        ec2_id = instance_ref['hostname']

        # Checking instance.
        self._live_migration_src_check(context, instance_ref)

        # Checking destination host.
        self._live_migration_dest_check(context, instance_ref, dest)

        # Common checking.
        self._live_migration_common_check(context, instance_ref, dest)

        # Changing instance_state.
        db.instance_set_state(context,
                              instance_id,
                              power_state.PAUSED,
                              'migrating')

        # Changing volume state
        for v in instance_ref['volumes']:
            db.volume_update(context,
                             v['id'],
                             {'status': 'migrating'})

        # Return value is necessary to send request to src
        # Check _schedule() in detail.
        src = instance_ref['host']
        return src

    def _live_migration_src_check(self, context, instance_ref):
        """Live migration check routine (for src host)"""

        # Checking instance is running.
        if power_state.RUNNING != instance_ref['state'] or \
           'running' != instance_ref['state_description']:
            msg = _('Instance(%s) is not running')
            ec2_id = instance_ref['hostname']
            raise exception.Invalid(msg % ec2_id)

        # Checing volume node is running when any volumes are mounted
        # to the instance.
        if len(instance_ref['volumes']) != 0:
            services = db.service_get_all_by_topic(context, 'volume')
            if len(services) < 1 or  not self.service_is_up(services[0]):
                msg = _('volume node is not alive(time synchronize problem?)')
                raise exception.Invalid(msg)

        # Checking src host is alive.
        src = instance_ref['host']
        services = db.service_get_all_by_topic(context, 'compute')
        services = [service for service in services if service.host == src]
        if len(services) < 1 or not self.service_is_up(services[0]):
            msg = _('%s is not alive(time synchronize problem?)')
            raise exception.Invalid(msg % src)

    def _live_migration_dest_check(self, context, instance_ref, dest):
        """Live migration check routine (for destination host)"""

        # Checking dest exists and compute node.
        dservice_refs = db.service_get_all_by_host(context, dest)
        if len(dservice_refs) <= 0:
            msg = _('%s does not exists.')
            raise exception.Invalid(msg % dest)

        dservice_ref = dservice_refs[0]
        if dservice_ref['topic'] != 'compute':
            msg = _('%s must be compute node')
            raise exception.Invalid(msg % dest)

        # Checking dest host is alive.
        if not self.service_is_up(dservice_ref):
            msg = _('%s is not alive(time synchronize problem?)')
            raise exception.Invalid(msg % dest)

        # Checking whether The host where instance is running
        # and dest is not same.
        src = instance_ref['host']
        if dest == src:
            ec2_id = instance_ref['hostname']
            msg = _('%s is where %s is running now. choose other host.')
            raise exception.Invalid(msg % (dest, ec2_id))

        # Checking dst host still has enough capacities.
        self.has_enough_resource(context, instance_ref, dest)

    def _live_migration_common_check(self, context, instance_ref, dest):
        """
           Live migration check routine.
           Below pre-checkings are followed by
           http://wiki.libvirt.org/page/TodoPreMigrationChecks

        """

        # Checking dest exists.
        dservice_refs = db.service_get_all_by_host(context, dest)
        if len(dservice_refs) <= 0:
            msg = _('%s does not exists.')
            raise exception.Invalid(msg % dest)
        dservice_ref = dservice_refs[0]

        # Checking original host( where instance was launched at) exists.
        orighost = instance_ref['launched_on']
        oservice_refs = db.service_get_all_by_host(context, orighost)
        if len(oservice_refs) <= 0:
            msg = _('%s(where instance was launched at) does not exists.')
            raise exception.Invalid(msg % orighost)
        oservice_ref = oservice_refs[0]

        # Checking hypervisor is same.
        otype = oservice_ref['hypervisor_type']
        dtype = dservice_ref['hypervisor_type']
        if otype != dtype:
            msg = _('Different hypervisor type(%s->%s)')
            raise exception.Invalid(msg % (otype, dtype))

        # Checkng hypervisor version.
        oversion = oservice_ref['hypervisor_version']
        dversion = dservice_ref['hypervisor_version']
        if oversion > dversion:
            msg = _('Older hypervisor version(%s->%s)')
            raise exception.Invalid(msg % (oversion, dversion))

        # Checking cpuinfo.
        cpu_info = oservice_ref['cpu_info']
        try:
            rpc.call(context,
                     db.queue_get_for(context, FLAGS.compute_topic, dest),
                     {"method": 'compare_cpu',
                      "args": {'cpu_info': cpu_info}})

        except rpc.RemoteError, e:
            msg = _(("""%s doesnt have compatibility to %s"""
                     """(where %s was launched at)"""))
            ec2_id = instance_ref['hostname']
            src = instance_ref['host']
            logging.error(msg % (dest, src, ec2_id))
            raise e

    def has_enough_resource(self, context, instance_ref, dest):
        """ Check if destination host has enough resource for live migration"""

        # Getting instance information
        ec2_id = instance_ref['hostname']
        vcpus = instance_ref['vcpus']
        mem = instance_ref['memory_mb']
        hdd = instance_ref['local_gb']

        # Gettin host information
        service_refs = db.service_get_all_by_host(context, dest)
        if len(service_refs) <= 0:
            msg = _('%s does not exists.')
            raise exception.Invalid(msg % dest)
        service_ref = service_refs[0]

        total_cpu = int(service_ref['vcpus'])
        total_mem = int(service_ref['memory_mb'])
        total_hdd = int(service_ref['local_gb'])

        instances_ref = db.instance_get_all_by_host(context, dest)
        for i_ref in instances_ref:
            total_cpu -= int(i_ref['vcpus'])
            total_mem -= int(i_ref['memory_mb'])
            total_hdd -= int(i_ref['local_gb'])

        # Checking host has enough information
        logging.debug('host(%s) remains vcpu:%s mem:%s hdd:%s,' %
                      (dest, total_cpu, total_mem, total_hdd))
        logging.debug('instance(%s) has vcpu:%s mem:%s hdd:%s,' %
                      (ec2_id, vcpus, mem, hdd))

        if total_cpu <= vcpus or total_mem <= mem or total_hdd <= hdd:
            msg = '%s doesnt have enough resource for %s' % (dest, ec2_id)
            raise exception.NotEmpty(msg)

        logging.debug(_('%s has_enough_resource() for %s') % (dest, ec2_id))
