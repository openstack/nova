# Copyright 2011 OpenStack LLC.
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

import common

from nova import db
from nova import flags
from nova import log as logging
from nova import wsgi
from nova.scheduler import api


FLAGS = flags.FLAGS


def _filter_keys(item, keys):
    """
    Filters all model attributes except for keys
    item is a dict

    """
    return dict((k, v) for k, v in item.iteritems() if k in keys)


def _exclude_keys(item, keys):
    return dict((k, v) for k, v in item.iteritems() if k not in keys)


def _scrub_zone(zone):
    return _filter_keys(zone, ('id', 'api_url'))


class Controller(wsgi.Controller):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "zone": ["id", "api_url", "name", "capabilities"]}}}

    def index(self, req):
        """Return all zones in brief"""
        # Ask the ZoneManager in the Scheduler for most recent data,
        # or fall-back to the database ...
        items = api.API.get_zone_list(req.environ['nova.context'])
        if not items:
            items = db.zone_get_all(req.environ['nova.context'])

        items = common.limited(items, req)
        items = [_exclude_keys(item, ['username', 'password'])
                      for item in items]
        return dict(zones=items)

    def detail(self, req):
        """Return all zones in detail"""
        return self.index(req)

    def info(self, req):
        """Return name and capabilities for this zone."""
        items = api.API.get_zone_capabilities(req.environ['nova.context'])

        zone = dict(name=FLAGS.zone_name)
        caps = FLAGS.zone_capabilities
        for cap in caps:
            key_values = cap.split('=')
            zone[key_values[0]] = key_values[1]
        for item, (min_value, max_value) in items.iteritems():
            zone[item] = "%s,%s" % (min_value, max_value)
        return dict(zone=zone)

    def show(self, req, id):
        """Return data about the given zone id"""
        zone_id = int(id)
        zone = db.zone_get(req.environ['nova.context'], zone_id)
        return dict(zone=_scrub_zone(zone))

    def delete(self, req, id):
        zone_id = int(id)
        db.zone_delete(req.environ['nova.context'], zone_id)
        return {}

    def create(self, req):
        context = req.environ['nova.context']
        env = self._deserialize(req.body, req.get_content_type())
        zone = db.zone_create(context, env["zone"])
        return dict(zone=_scrub_zone(zone))

    def update(self, req, id):
        context = req.environ['nova.context']
        env = self._deserialize(req.body, req.get_content_type())
        zone_id = int(id)
        zone = db.zone_update(context, zone_id, env["zone"])
        return dict(zone=_scrub_zone(zone))
