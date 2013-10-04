# Copyright (c) 2011-2012 OpenStack Foundation
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

from oslo.config import cfg

from nova import db
from nova.scheduler import filters

CONF = cfg.CONF
CONF.import_opt('default_availability_zone', 'nova.availability_zones')


class AvailabilityZoneFilter(filters.BaseHostFilter):
    """Filters Hosts by availability zone.

    Works with aggregate metadata availability zones, using the key
    'availability_zone'
    Note: in theory a compute node can be part of multiple availability_zones
    """

    # Availability zones do not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        spec = filter_properties.get('request_spec', {})
        props = spec.get('instance_properties', {})
        availability_zone = props.get('availability_zone')

        if availability_zone:
            context = filter_properties['context'].elevated()
            metadata = db.aggregate_metadata_get_by_host(
                         context, host_state.host, key='availability_zone')
            if 'availability_zone' in metadata:
                return availability_zone in metadata['availability_zone']
            else:
                return availability_zone == CONF.default_availability_zone

        return True
