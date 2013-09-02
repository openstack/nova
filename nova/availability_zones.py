# Copyright (c) 2012 OpenStack Foundation
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

"""Availability zone helper functions."""

from oslo.config import cfg

from nova import db
from nova.openstack.common import memorycache

# NOTE(vish): azs don't change that often, so cache them for an hour to
#             avoid hitting the db multiple times on every request.
AZ_CACHE_SECONDS = 60 * 60
MC = None

availability_zone_opts = [
    cfg.StrOpt('internal_service_availability_zone',
               default='internal',
               help='availability_zone to show internal services under'),
    cfg.StrOpt('default_availability_zone',
               default='nova',
               help='default compute node availability_zone'),
    ]

CONF = cfg.CONF
CONF.register_opts(availability_zone_opts)


def _get_cache():
    global MC

    if MC is None:
        MC = memorycache.get_client()

    return MC


def reset_cache():
    """Reset the cache, mainly for testing purposes and update
    availability_zone for host aggregate
    """

    global MC

    MC = None


def _make_cache_key(host):
    return "azcache-%s" % host.encode('utf-8')


def set_availability_zones(context, services):
    # Makes sure services isn't a sqlalchemy object
    services = [dict(service.iteritems()) for service in services]
    metadata = db.aggregate_host_get_by_metadata_key(context,
            key='availability_zone')
    for service in services:
        az = CONF.internal_service_availability_zone
        if service['topic'] == "compute":
            if metadata.get(service['host']):
                az = u','.join(list(metadata[service['host']]))
            else:
                az = CONF.default_availability_zone
                # update the cache
                cache = _get_cache()
                cache_key = _make_cache_key(service['host'])
                cache.delete(cache_key)
                cache.set(cache_key, az, AZ_CACHE_SECONDS)
        service['availability_zone'] = az
    return services


def get_host_availability_zone(context, host, conductor_api=None):
    if conductor_api:
        metadata = conductor_api.aggregate_metadata_get_by_host(
            context, host, key='availability_zone')
    else:
        metadata = db.aggregate_metadata_get_by_host(
            context, host, key='availability_zone')
    if 'availability_zone' in metadata:
        az = list(metadata['availability_zone'])[0]
    else:
        az = CONF.default_availability_zone
    return az


def get_availability_zones(context, get_only_available=False):
    """Return available and unavailable zones on demands.

       :param get_only_available: flag to determine whether to return
           available zones only, default False indicates return both
           available zones and not available zones, True indicates return
           available zones only
    """
    enabled_services = db.service_get_all(context, False)
    enabled_services = set_availability_zones(context, enabled_services)

    available_zones = []
    for zone in [service['availability_zone'] for service
                 in enabled_services]:
        if zone not in available_zones:
            available_zones.append(zone)

    if not get_only_available:
        disabled_services = db.service_get_all(context, True)
        disabled_services = set_availability_zones(context, disabled_services)
        not_available_zones = []
        zones = [service['availability_zone'] for service in disabled_services
                if service['availability_zone'] not in available_zones]
        for zone in zones:
            if zone not in not_available_zones:
                not_available_zones.append(zone)
        return (available_zones, not_available_zones)
    else:
        return available_zones


def get_instance_availability_zone(context, instance):
    """Return availability zone of specified instance."""
    host = str(instance.get('host'))
    if not host:
        return None

    cache_key = _make_cache_key(host)
    cache = _get_cache()
    az = cache.get(cache_key)
    if not az:
        elevated = context.elevated()
        az = get_host_availability_zone(elevated, host)
        cache.set(cache_key, az, AZ_CACHE_SECONDS)
    return az
