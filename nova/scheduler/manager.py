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
import novatools
import thread

from datetime import datetime
from eventlet.greenpool import GreenPool

from nova import db
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils

LOG = logging.getLogger('nova.scheduler.manager')
FLAGS = flags.FLAGS
flags.DEFINE_string('scheduler_driver',
                    'nova.scheduler.chance.ChanceScheduler',
                    'Driver to use for the scheduler')
flags.DEFINE_integer('zone_db_check_interval',
                    60,
                    'Seconds between getting fresh zone info from db.')


class ZoneState(object):
    """Holds the state of all connected child zones."""
    def __init__(self):
        self.is_active = True
        self.name = None
        self.capabilities = None
        self.retry = 0
        self.last_seen = datetime.min
 
    def update(self, zone):
        """Update zone credentials from db"""
        self.zone_id = zone.id
        self.api_url = zone.api_url
        self.username = zone.username
        self.password = zone.password
 

def _poll_zone(zone):
    """Eventlet worker to poll a zone."""
    logging.debug("_POLL_ZONE: STARTING")
    os = novatools.OpenStack(zone.username, zone.password, zone.api_url)
    zone_metadata = os.zones.info()
    logging.debug("_POLL_ZONE: GOT %s" % zone_metadata._info)

    # Stuff this in our cache.


class ZoneManager(object):
    """Keeps the zone states updated."""
    def __init__(self):
        self.last_zone_db_check = datetime.min
        self.zone_states = {}

    def _refresh_from_db(self, context):
        """Make our zone state map match the db."""
        # Add/update existing zones ...
        zones = db.zone_get_all(context)
        existing = self.zone_states.keys()
        db_keys = []
        for zone in zones:
            db_keys.append(zone.id)
            if zone.id not in existing:
                self.zone_states[zone.id] = ZoneState()
            self.zone_states[zone.id].update(zone)

        # Cleanup zones removed from db ...
        for zone_id in self.zone_states.keys():
            if zone_id not in db_keys:
                del self.zone_states[zone_id]
 
    def _poll_zones(self, context):
        """Try to connect to each child zone and get update."""

        green_pool = GreenPool()
        green_pool.imap(_poll_zone, self.zone_states.values())

    def ping(self, context=None):
        """Ping should be called periodically to update zone status."""
        logging.debug("ZoneManager PING")
        diff = datetime.now() - self.last_zone_db_check
        if diff.seconds >=  FLAGS.zone_db_check_interval:
            logging.debug("ZoneManager RECHECKING DB ")
            self.last_zone_db_check = datetime.now()
            self._refresh_from_db(context)
        self._poll_zones(context)
            

class SchedulerManager(manager.Manager):
    """Chooses a host to run instances on."""
    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
        self.driver = utils.import_object(scheduler_driver)
        self.zone_manager = ZoneManager()
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def __getattr__(self, key):
        """Converts all method calls to use the schedule method"""
        return functools.partial(self._schedule, key)

    def periodic_tasks(self, context=None):
        """Poll child zones periodically to get status."""
        self.zone_manager.ping(context)

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
        LOG.debug(_("Casting to %(topic)s %(host)s for %(method)s") % locals())
