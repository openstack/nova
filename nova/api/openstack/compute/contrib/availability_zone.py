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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import availability_zones
from nova import objects
from nova import servicegroup

CONF = cfg.CONF

authorize_list = extensions.extension_authorizer('compute',
                                                 'availability_zone:list')
authorize_detail = extensions.extension_authorizer('compute',
                                                   'availability_zone:detail')


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
            result.append({'zoneName': zone,
                           'zoneState': {'available': is_available},
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
        return {'availabilityZoneInfo': filtered_available_zones +
                                        filtered_not_available_zones}

    def _describe_availability_zones_verbose(self, context, **kwargs):
        ctxt = context.elevated()
        available_zones, not_available_zones = \
            availability_zones.get_availability_zones(ctxt)

        # Available services
        enabled_services = objects.ServiceList.get_all(context, disabled=False)
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
            for host in zone_hosts.get(zone, []):
                hosts[host] = {}
                for service in host_services[zone + host]:
                    alive = self.servicegroup_api.service_is_up(service)
                    hosts[host][service['binary']] = {'available': alive,
                                      'active': True != service['disabled'],
                                      'updated_at': service['updated_at']}
            result.append({'zoneName': zone,
                           'zoneState': {'available': True},
                           "hosts": hosts})

        for zone in not_available_zones:
            result.append({'zoneName': zone,
                           'zoneState': {'available': False},
                           "hosts": None})
        return {'availabilityZoneInfo': result}

    def index(self, req):
        """Returns a summary list of availability zone."""
        context = req.environ['nova.context']
        authorize_list(context)

        return self._describe_availability_zones(context)

    def detail(self, req):
        """Returns a detailed list of availability zone."""
        context = req.environ['nova.context']
        authorize_detail(context)

        return self._describe_availability_zones_verbose(context)


class Availability_zone(extensions.ExtensionDescriptor):
    """1. Add availability_zone to the Create Server v1.1 API.
       2. Add availability zones describing.
    """

    name = "AvailabilityZone"
    alias = "os-availability-zone"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "availabilityzone/api/v1.1")
    updated = "2012-12-21T00:00:00Z"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-availability-zone',
                                       AvailabilityZoneController(),
                                       collection_actions={'detail': 'GET'})
        resources.append(res)

        return resources
