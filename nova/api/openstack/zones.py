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

import json
import urlparse

from nova import crypto
from nova import db
from nova import exception
from nova import flags
from nova import log as logging

from nova.compute import api as compute
from nova.scheduler import api

from nova.api.openstack import create_instance_helper as helper
from nova.api.openstack import common
from nova.api.openstack import wsgi


FLAGS = flags.FLAGS


LOG = logging.getLogger('nova.api.openstack.zones')


def _filter_keys(item, keys):
    """
    Filters all model attributes except for keys
    item is a dict

    """
    return dict((k, v) for k, v in item.iteritems() if k in keys)


def _exclude_keys(item, keys):
    return dict((k, v) for k, v in item.iteritems() if k not in keys)


def _scrub_zone(zone):
    return _exclude_keys(zone, ('username', 'password', 'created_at',
                    'deleted', 'deleted_at', 'updated_at'))


def check_encryption_key(func):
    def wrapped(*args, **kwargs):
        if not FLAGS.build_plan_encryption_key:
            raise exception.Error(_("--build_plan_encryption_key not set"))
        return func(*args, **kwargs)
    return wrapped


class Controller(object):
    """Controller for Zone resources."""

    def __init__(self):
        self.compute_api = compute.API()
        self.helper = helper.CreateInstanceHelper(self)

    def index(self, req):
        """Return all zones in brief"""
        # Ask the ZoneManager in the Scheduler for most recent data,
        # or fall-back to the database ...
        items = api.get_zone_list(req.environ['nova.context'])
        items = common.limited(items, req)
        items = [_scrub_zone(item) for item in items]
        return dict(zones=items)

    def detail(self, req):
        """Return all zones in detail"""
        return self.index(req)

    def info(self, req):
        """Return name and capabilities for this zone."""
        items = api.get_zone_capabilities(req.environ['nova.context'])

        zone = dict(name=FLAGS.zone_name)
        caps = FLAGS.zone_capabilities
        for cap in caps:
            key, value = cap.split('=')
            zone[key] = value
        for item, (min_value, max_value) in items.iteritems():
            zone[item] = "%s,%s" % (min_value, max_value)
        return dict(zone=zone)

    def show(self, req, id):
        """Return data about the given zone id"""
        zone_id = int(id)
        zone = api.zone_get(req.environ['nova.context'], zone_id)
        return dict(zone=_scrub_zone(zone))

    def delete(self, req, id):
        """Delete a child zone entry."""
        zone_id = int(id)
        api.zone_delete(req.environ['nova.context'], zone_id)
        return {}

    def create(self, req, body):
        """Create a child zone entry."""
        context = req.environ['nova.context']
        zone = api.zone_create(context, body["zone"])
        return dict(zone=_scrub_zone(zone))

    def update(self, req, id, body):
        """Update a child zone entry."""
        context = req.environ['nova.context']
        zone_id = int(id)
        zone = api.zone_update(context, zone_id, body["zone"])
        return dict(zone=_scrub_zone(zone))

    def boot(self, req, body):
        """Creates a new server for a given user while being Zone aware.

        Returns a reservation ID (a UUID).
        """
        result = None
        extra_values, result = self.helper.create_instance(req, body,
                                self.compute_api.create_all_at_once)

        reservation_id = result
        return {'reservation_id': reservation_id}

    @check_encryption_key
    def select(self, req, body):
        """Returns a weighted list of costs to create instances
           of desired capabilities."""
        ctx = req.environ['nova.context']
        specs = json.loads(body)
        build_plan = api.select(ctx, specs=specs)
        cooked = self._scrub_build_plan(build_plan)
        return {"weights": cooked}

    def _scrub_build_plan(self, build_plan):
        """Remove all the confidential data and return a sanitized
        version of the build plan. Include an encrypted full version
        of the weighting entry so we can get back to it later."""
        encryptor = crypto.encryptor(FLAGS.build_plan_encryption_key)
        cooked = []
        for entry in build_plan:
            json_entry = json.dumps(entry)
            cipher_text = encryptor(json_entry)
            cooked.append(dict(weight=entry['weight'],
                blob=cipher_text))
        return cooked

    def _image_ref_from_req_data(self, data):
        return data['server']['imageId']

    def _flavor_id_from_req_data(self, data):
        return data['server']['flavorId']

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self.helper._get_server_admin_password_old_style(server)


class ControllerV11(Controller):
    """Controller for 1.1 Zone resources."""

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self.helper._get_server_admin_password_new_style(server)

    def _image_ref_from_req_data(self, data):
        return data['server']['imageRef']

    def _flavor_id_from_req_data(self, data):
        return data['server']['flavorRef']


def create_resource(version):
    controller = {
        '1.0': Controller,
        '1.1': ControllerV11,
    }[version]()

    metadata = {
        "attributes": {
            "zone": ["id", "api_url", "name", "capabilities"],
        },
    }

    body_serializers = {
        'application/xml': wsgi.XMLDictSerializer(xmlns=wsgi.XMLNS_V10,
                                                  metadata=metadata),
    }
    serializer = wsgi.ResponseSerializer(body_serializers)

    body_deserializers = {
        'application/xml': helper.ServerXMLDeserializer(),
    }
    deserializer = wsgi.RequestDeserializer(body_deserializers)

    return wsgi.Resource(controller, deserializer, serializer)
