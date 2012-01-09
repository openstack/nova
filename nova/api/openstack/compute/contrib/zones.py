# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""The zones extension."""

import json

from nova.api.openstack import common
from nova.api.openstack.compute import servers
from nova.api.openstack import extensions
from nova.api.openstack import xmlutil
from nova.api.openstack import wsgi
from nova.compute import api as compute
from nova import crypto
from nova import exception
from nova import flags
from nova import log as logging
import nova.scheduler.api


LOG = logging.getLogger("nova.api.openstack.compute.contrib.zones")
FLAGS = flags.FLAGS


class CapabilitySelector(object):
    def __call__(self, obj, do_raise=False):
        return [(k, v) for k, v in obj.items()
                if k not in ('id', 'api_url', 'name', 'capabilities')]


def make_zone(elem):
    elem.set('id')
    elem.set('api_url')
    elem.set('name')
    elem.set('capabilities')

    cap = xmlutil.SubTemplateElement(elem, xmlutil.Selector(0),
                                     selector=CapabilitySelector())
    cap.text = 1


zone_nsmap = {None: wsgi.XMLNS_V10}


class ZoneTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('zone', selector='zone')
        make_zone(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=zone_nsmap)


class ZonesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('zones')
        elem = xmlutil.SubTemplateElement(root, 'zone', selector='zones')
        make_zone(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=zone_nsmap)


class WeightsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('weights')
        weight = xmlutil.SubTemplateElement(root, 'weight', selector='weights')
        blob = xmlutil.SubTemplateElement(weight, 'blob')
        blob.text = 'blob'
        inner_weight = xmlutil.SubTemplateElement(weight, 'weight')
        inner_weight.text = 'weight'
        return xmlutil.MasterTemplate(root, 1, nsmap=zone_nsmap)


def _filter_keys(item, keys):
    """
    Filters all model attributes except for keys
    item is a dict

    """
    return dict((k, v) for k, v in item.iteritems() if k in keys)


def _exclude_keys(item, keys):
    return dict((k, v) for k, v in item.iteritems() if k and (k not in keys))


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

    @wsgi.serializers(xml=ZonesTemplate)
    def index(self, req):
        """Return all zones in brief"""
        # Ask the ZoneManager in the Scheduler for most recent data,
        # or fall-back to the database ...
        items = nova.scheduler.api.get_zone_list(req.environ['nova.context'])
        items = common.limited(items, req)
        items = [_scrub_zone(item) for item in items]
        return dict(zones=items)

    @wsgi.serializers(xml=ZonesTemplate)
    def detail(self, req):
        """Return all zones in detail"""
        return self.index(req)

    @wsgi.serializers(xml=ZoneTemplate)
    def info(self, req):
        """Return name and capabilities for this zone."""
        context = req.environ['nova.context']
        items = nova.scheduler.api.get_zone_capabilities(context)

        zone = dict(name=FLAGS.zone_name)
        caps = FLAGS.zone_capabilities
        for cap in caps:
            key, value = cap.split('=')
            zone[key] = value
        for item, (min_value, max_value) in items.iteritems():
            zone[item] = "%s,%s" % (min_value, max_value)
        return dict(zone=zone)

    @wsgi.serializers(xml=ZoneTemplate)
    def show(self, req, id):
        """Return data about the given zone id"""
        zone_id = int(id)
        context = req.environ['nova.context']
        zone = nova.scheduler.api.zone_get(context, zone_id)
        return dict(zone=_scrub_zone(zone))

    def delete(self, req, id):
        """Delete a child zone entry."""
        zone_id = int(id)
        nova.scheduler.api.zone_delete(req.environ['nova.context'], zone_id)
        return {}

    @wsgi.serializers(xml=ZoneTemplate)
    @wsgi.deserializers(xml=servers.CreateDeserializer)
    def create(self, req, body):
        """Create a child zone entry."""
        context = req.environ['nova.context']
        zone = nova.scheduler.api.zone_create(context, body["zone"])
        return dict(zone=_scrub_zone(zone))

    @wsgi.serializers(xml=ZoneTemplate)
    def update(self, req, id, body):
        """Update a child zone entry."""
        context = req.environ['nova.context']
        zone_id = int(id)
        zone = nova.scheduler.api.zone_update(context, zone_id, body["zone"])
        return dict(zone=_scrub_zone(zone))

    @wsgi.serializers(xml=WeightsTemplate)
    @check_encryption_key
    def select(self, req, body):
        """Returns a weighted list of costs to create instances
           of desired capabilities."""
        ctx = req.environ['nova.context']
        specs = json.loads(body)
        build_plan = nova.scheduler.api.select(ctx, specs=specs)
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


class ZonesXMLSerializer(xmlutil.XMLTemplateSerializer):
    def index(self):
        return ZonesTemplate()

    def detail(self):
        return ZonesTemplate()

    def select(self):
        return WeightsTemplate()

    def default(self):
        return ZoneTemplate()


class Zones(extensions.ExtensionDescriptor):
    """Enables zones-related functionality such as adding child zones,
    listing child zones, getting the capabilities of the local zone,
    and returning build plans to parent zones' schedulers
    """

    name = "Zones"
    alias = "os-zones"
    namespace = "http://docs.openstack.org/compute/ext/zones/api/v1.1"
    updated = "2011-09-21T00:00:00+00:00"
    admin_only = True

    def get_resources(self):
        #NOTE(bcwaldon): This resource should be prefixed with 'os-'
        coll_actions = {
            'detail': 'GET',
            'info': 'GET',
            'select': 'POST',
        }

        res = extensions.ResourceExtension('zones',
                                           Controller(),
                                           collection_actions=coll_actions)
        return [res]
