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

from nova.api.openstack import wsgi
from nova import availability_zones
from nova import compute
import nova.conf
from nova.policies import availability_zone as az_policies
from nova import servicegroup

CONF = nova.conf.CONF
ATTRIBUTE_NAME = "availability_zone"


class AvailabilityZoneController(wsgi.Controller):
    """The Availability Zone API controller for the OpenStack API."""

    def __init__(self):
        super(AvailabilityZoneController, self).__init__()
        self.servicegroup_api = servicegroup.API()
        self.host_api = compute.HostAPI()

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
        enabled_services = self.host_api.service_get_all(
            context, {'disabled': False}, set_zones=True, all_cells=True)

        zone_hosts = {}
        host_services = {}
        api_services = ('nova-osapi_compute', 'nova-ec2', 'nova-metadata')
        for service in enabled_services:
            if service.binary in api_services:
                # Skip API services in the listing since they are not
                # maintained in the same way as other services
                continue
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

    @wsgi.expected_errors(())
    def index(self, req):
        """Returns a summary list of availability zone."""
        context = req.environ['nova.context']
        context.can(az_policies.POLICY_ROOT % 'list')

        return self._describe_availability_zones(context)

    @wsgi.expected_errors(())
    def detail(self, req):
        """Returns a detailed list of availability zone."""
        context = req.environ['nova.context']
        context.can(az_policies.POLICY_ROOT % 'detail')

        return self._describe_availability_zones_verbose(context)
