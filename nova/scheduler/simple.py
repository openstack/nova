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
Simple Scheduler - for Volumes

Note: Deprecated in Folsom.  Will be removed along with nova-volumes
"""

from nova.common import deprecated
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.scheduler import chance
from nova.scheduler import driver
from nova import utils


simple_scheduler_opts = [
    cfg.IntOpt("max_gigabytes",
               default=10000,
               help="maximum number of volume gigabytes to allow per host"),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(simple_scheduler_opts)


class SimpleScheduler(chance.ChanceScheduler):
    """Implements Naive Scheduler that tries to find least loaded host."""

    def schedule_run_instance(self, context, request_spec, admin_password,
                              injected_files, requested_networks,
                              is_first_time, filter_properties):
        deprecated.warn(_('SimpleScheduler now only covers volume scheduling '
                'and is deprecated in Folsom. Non-volume functionality in '
                'SimpleScheduler has been replaced by FilterScheduler'))
        super(SimpleScheduler, self).schedule_run_instance(context,
                request_spec, admin_password, injected_files,
                requested_networks, is_first_time, filter_properties)

    def schedule_create_volume(self, context, volume_id, snapshot_id,
                               image_id):
        """Picks a host that is up and has the fewest volumes."""
        deprecated.warn(_('nova-volume functionality is deprecated in Folsom '
                'and will be removed in Grizzly.  Volumes are now handled '
                'by Cinder'))
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
                    volume_id=volume_id, snapshot_id=snapshot_id,
                    image_id=image_id)
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
                        'create_volume', volume_id=volume_id,
                        snapshot_id=snapshot_id, image_id=image_id)
                return None
        msg = _("Is the appropriate service running?")
        raise exception.NoValidHost(reason=msg)
