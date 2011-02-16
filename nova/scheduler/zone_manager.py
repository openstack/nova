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
ZoneManager oversees all communications with child Zones.
"""

import novatools
import thread

from datetime import datetime
from eventlet.greenpool import GreenPool

from nova import db
from nova import flags
from nova import log as logging

FLAGS = flags.FLAGS
flags.DEFINE_integer('zone_db_check_interval', 60,
                    'Seconds between getting fresh zone info from db.')
flags.DEFINE_integer('zone_failures_to_offline', 3,
             'Number of consecutive errors before marking zone offline')


class ZoneState(object):
    """Holds the state of all connected child zones."""
    def __init__(self):
        self.is_active = True
        self.name = None
        self.capabilities = None
        self.attempt = 0
        self.last_seen = datetime.min
        self.last_exception = None
        self.last_exception_time = None
 
    def update_credentials(self, zone):
        """Update zone credentials from db"""
        self.zone_id = zone.id
        self.api_url = zone.api_url
        self.username = zone.username
        self.password = zone.password
 
    def update_metadata(self, zone_metadata):
        """Update zone metadata after successful communications with
           child zone."""
        self.last_seen = datetime.now()
        self.attempt = 0
        self.name = zone_metadata["name"]
        self.capabilities = zone_metadata["capabilities"]
        self.is_active = True

    def log_error(self, exception):
        """Something went wrong. Check to see if zone should be
           marked as offline."""
        self.last_exception = exception
        self.last_exception_time = datetime.now()
        logging.warning(_("%s error talking to zone %s") % (exception,
            zone.api_url, FLAGS.zone_failures_to_offline))

       self.attempt += 1
        if self.attempt >= FLAGS.zone_failures_to_offline:
           self.is_active = False
           logging.error(_("No answer from zone %s after %d "
               "attempts. Marking inactive.") % (zone.api_url,
               FLAGS.zone_failures_to_offline))

def _poll_zone(zone):
    """Eventlet worker to poll a zone."""
    logging.debug("_POLL_ZONE: STARTING")
    os = novatools.OpenStack(zone.username, zone.password, zone.api_url)
    try:
        zone.update_metadata(os.zones.info()._info)
    except Exception, e:
        zone.log_error(e)

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
            self.zone_states[zone.id].update_credentials(zone)

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
