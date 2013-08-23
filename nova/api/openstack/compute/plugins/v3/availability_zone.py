# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

from oslo.config import cfg

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import availability_zones
from nova import db
from nova import servicegroup

CONF = cfg.CONF
ALIAS = "os-availability-zone"
ATTRIBUTE_NAME = "%s:availability_zone" % ALIAS
authorize_list = extensions.extension_authorizer('compute',
                                                 'v3:' + ALIAS + ':list')
authorize_detail = extensions.extension_authorizer('compute',
                                                   'v3:' + ALIAS + ':detail')


def make_availability_zone(elem):
    elem.set('name', 'zone_name')

    zoneStateElem = xmlutil.SubTemplateElement(elem, 'zone_state',
                                               selector='zone_state')
    zoneStateElem.set('available')

    hostsElem = xmlutil.SubTemplateElement(elem, 'hosts', selector='hosts')
    hostElem = xmlutil.SubTemplateElement(hostsElem, 'host',
                                          selector=xmlutil.get_items)
    hostElem.set('name', 0)

    svcsElem = xmlutil.SubTemplateElement(hostElem, 'services', selector=1)
    svcElem = xmlutil.SubTemplateElement(svcsElem, 'service',
                                         selector=xmlutil.get_items)
    svcElem.set('name', 0)

    svcStateElem = xmlutil.SubTemplateElement(svcElem, 'service_state',
                                              selector=1)
    svcStateElem.set('available')
    svcStateElem.set('active')
    svcStateElem.set('updated_at')

    # Attach metadata node
    elem.append(common.MetadataTemplate())


class AvailabilityZonesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('availability_zones')
        zoneElem = xmlutil.SubTemplateElement(root, 'availability_zone',
            selector='availability_zone_info')
        make_availability_zone(zoneElem)
        return xmlutil.MasterTemplate(root, 1, nsmap={
            AvailabilityZone.alias: AvailabilityZone.namespace})


class AvailabilityZoneController(wsgi.Controller):
    """The Availability Zone API controller for the OpenStack API."""

    def __init__(self):
        super(AvailabilityZoneController, self).__init__()
        self.servicegroup_api = servicegroup.API()

    def _get_filtered_availability_zones(self, zones, is_available):
        result = []
        for zone in zones:
            # Hide internal_service_availability_zone
            if zone == CONF.internal_service_availability_zone:
                continue
            result.append({'zone_name': zone,
                           'zone_state': {'available': is_available},
                           "hosts": None})
        return result

    def _describe_availability_zones(self, context, **kwargs):
        ctxt = context.elevated()
        available_zones, not_available_zones = \
            availability_zones.get_availability_zones(ctxt)

        filtered_available_zones = \
            self._get_filtered_availability_zones(available_zones, True)
        filtered_not_available_zones = \
            self._get_filtered_availability_zones(not_available_zones, False)
        return {'availability_zone_info': filtered_available_zones +
                                        filtered_not_available_zones}

    def _describe_availability_zones_verbose(self, context, **kwargs):
        ctxt = context.elevated()
        available_zones, not_available_zones = \
            availability_zones.get_availability_zones(ctxt)

        # Available services
        enabled_services = db.service_get_all(context, False)
        enabled_services = availability_zones.set_availability_zones(context,
                enabled_services)
        zone_hosts = {}
        host_services = {}
        for service in enabled_services:
            zone_hosts.setdefault(service['availability_zone'], [])
            if service['host'] not in zone_hosts[service['availability_zone']]:
                zone_hosts[service['availability_zone']].append(
                    service['host'])

            host_services.setdefault(service['availability_zone'] +
                    service['host'], [])
            host_services[service['availability_zone'] + service['host']].\
                    append(service)

        result = []
        for zone in available_zones:
            hosts = {}
            for host in zone_hosts[zone]:
                hosts[host] = {}
                for service in host_services[zone + host]:
                    alive = self.servicegroup_api.service_is_up(service)
                    hosts[host][service['binary']] = {'available': alive,
                                      'active': True != service['disabled'],
                                      'updated_at': service['updated_at']}
            result.append({'zone_name': zone,
                           'zone_state': {'available': True},
                           "hosts": hosts})

        for zone in not_available_zones:
            result.append({'zone_name': zone,
                           'zone_state': {'available': False},
                           "hosts": None})
        return {'availability_zone_info': result}

    @extensions.expected_errors(())
    @wsgi.serializers(xml=AvailabilityZonesTemplate)
    def index(self, req):
        """Returns a summary list of availability zone."""
        context = req.environ['nova.context']
        authorize_list(context)

        return self._describe_availability_zones(context)

    @extensions.expected_errors(())
    @wsgi.serializers(xml=AvailabilityZonesTemplate)
    def detail(self, req):
        """Returns a detailed list of availability zone."""
        context = req.environ['nova.context']
        authorize_detail(context)

        return self._describe_availability_zones_verbose(context)


class AvailabilityZone(extensions.V3APIExtensionBase):
    """1. Add availability_zone to the Create Server API.
       2. Add availability zones describing.
    """

    name = "AvailabilityZone"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "availabilityzone/api/v3")
    version = 1

    def get_resources(self):
        resource = [extensions.ResourceExtension(ALIAS,
            AvailabilityZoneController(),
            collection_actions={'detail': 'GET'})]
        return resource

    def get_controller_extensions(self):
        """It's an abstract function V3APIExtensionBase and the extension
        will not be loaded without it.
        """
        return []

    def server_create(self, server_dict, create_kwargs):
        create_kwargs['availability_zone'] = server_dict.get(ATTRIBUTE_NAME)

    def server_xml_extract_server_deserialize(self, server_node, server_dict):
        availability_zone = server_node.getAttribute(ATTRIBUTE_NAME)
        if availability_zone:
            server_dict[ATTRIBUTE_NAME] = availability_zone
