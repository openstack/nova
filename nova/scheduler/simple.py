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
Simple Scheduler
"""

from nova import db
from nova import flags
from nova import exception
from nova.openstack.common import cfg
from nova.scheduler import driver
from nova.scheduler import chance
from nova import utils


simple_scheduler_opts = [
    cfg.IntOpt("max_cores",
               default=16,
               help="maximum number of instance cores to allow per host"),
    cfg.IntOpt("max_gigabytes",
               default=10000,
               help="maximum number of volume gigabytes to allow per host"),
    cfg.IntOpt("max_networks",
               default=1000,
               help="maximum number of networks to allow per host"),
    cfg.BoolOpt('skip_isolated_core_check',
                default=True,
                help='Allow overcommitting vcpus on isolated hosts'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(simple_scheduler_opts)


class SimpleScheduler(chance.ChanceScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def _schedule_instance(self, context, instance_opts, *_args, **_kwargs):
        """Picks a host that is up and has the fewest running instances."""
        elevated = context.elevated()

        availability_zone = instance_opts.get('availability_zone')

        zone, host = FLAGS.default_schedule_zone, None
        if availability_zone:
            zone, _x, host = availability_zone.partition(':')

        if host and context.is_admin:
            service = db.service_get_by_args(elevated, host, 'nova-compute')
            if not utils.service_is_up(service):
                raise exception.WillNotSchedule(host=host)
            return host

        results = db.service_get_all_compute_sorted(elevated)
        in_isolation = instance_opts['image_ref'] in FLAGS.isolated_images
        check_cores = not in_isolation or not FLAGS.skip_isolated_core_check
        if zone:
            results = [(service, cores) for (service, cores) in results
                       if service['availability_zone'] == zone]
        for result in results:
            (service, instance_cores) = result
            if in_isolation and service['host'] not in FLAGS.isolated_hosts:
                # isloated images run on isolated hosts
                continue
            if service['host'] in FLAGS.isolated_hosts and not in_isolation:
                # images that aren't isolated only run on general hosts
                continue
            if (check_cores and
                instance_cores + instance_opts['vcpus'] > FLAGS.max_cores):
                msg = _("Not enough allocatable CPU cores remaining")
                raise exception.NoValidHost(reason=msg)
            if utils.service_is_up(service) and not service['disabled']:
                return service['host']
        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)

    def schedule_run_instance(self, context, request_spec, *_args, **_kwargs):
        num_instances = request_spec.get('num_instances', 1)
        instances = []
        for num in xrange(num_instances):
            host = self._schedule_instance(context,
                    request_spec['instance_properties'], *_args, **_kwargs)
            request_spec['instance_properties']['launch_index'] = num
            instance_ref = self.create_instance_db_entry(context,
                    request_spec)
            driver.cast_to_compute_host(context, host, 'run_instance',
                    instance_uuid=instance_ref['uuid'], **_kwargs)
            instances.append(driver.encode_instance(instance_ref))
            # So if we loop around, create_instance_db_entry will actually
            # create a new entry, instead of assume it's been created
            # already
            del request_spec['instance_properties']['uuid']
        return instances

    def schedule_create_volume(self, context, volume_id, *_args, **_kwargs):
        """Picks a host that is up and has the fewest volumes."""
        elevated = context.elevated()

        volume_ref = db.volume_get(context, volume_id)
        availability_zone = volume_ref.get('availability_zone')

        zone, host = None, None
        if availability_zone:
            zone, _x, host = availability_zone.partition(':')
        if host and context.is_admin:
            service = db.service_get_by_args(elevated, host, 'nova-volume')
            if not utils.service_is_up(service):
                raise exception.WillNotSchedule(host=host)
            driver.cast_to_volume_host(context, host, 'create_volume',
                    volume_id=volume_id, **_kwargs)
            return None

        results = db.service_get_all_volume_sorted(elevated)
        if zone:
            results = [(service, gigs) for (service, gigs) in results
                       if service['availability_zone'] == zone]
        for result in results:
            (service, volume_gigabytes) = result
            if volume_gigabytes + volume_ref['size'] > FLAGS.max_gigabytes:
                msg = _("Not enough allocatable volume gigabytes remaining")
                raise exception.NoValidHost(reason=msg)
            if utils.service_is_up(service) and not service['disabled']:
                driver.cast_to_volume_host(context, service['host'],
                        'create_volume', volume_id=volume_id, **_kwargs)
                return None
        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)
