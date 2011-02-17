# Copyright 2010 OpenStack LLC.
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
import logging

from nova import flags
from nova import wsgi
from nova import db
from nova import rpc


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

    def _call_scheduler(self, method, context, params=None):
        """Generic handler for RPC calls to the scheduler.

        :param params: Optional dictionary of arguments to be passed to the
                       scheduler worker

        :retval: Result returned by scheduler worker
        """
        if not params:
            params = {}
        queue = FLAGS.scheduler_topic
        kwargs = {'method': method, 'args': params}
        return rpc.call(context, queue, kwargs)

    def index(self, req):
        """Return all zones in brief"""
        # Ask the ZoneManager in the Scheduler for most recent data.
        items = self._call_scheduler('get_zone_list',
                          req.environ['nova.context'])
        for item in items:
            item['api_url'] = item['api_url'].replace('\\/', '/')

        # Or fall-back to the database ...
        if len(items) == 0:
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
        return dict(zone=dict(name=FLAGS.zone_name,
                    capabilities=FLAGS.zone_capabilities))

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
        env = self._deserialize(req.body, req)
        zone = db.zone_create(context, env["zone"])
        return dict(zone=_scrub_zone(zone))

    def update(self, req, id):
        context = req.environ['nova.context']
        env = self._deserialize(req.body, req)
        zone_id = int(id)
        zone = db.zone_update(context, zone_id, env["zone"])
        return dict(zone=_scrub_zone(zone))
