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

import collections

from nova import cache_utils
import nova.conf
from nova import objects

# NOTE(vish): azs don't change that often, so cache them for an hour to
#             avoid hitting the db multiple times on every request.
AZ_CACHE_SECONDS = 60 * 60
MC = None

CONF = nova.conf.CONF


def _get_cache():
    global MC

    if MC is None:
        MC = cache_utils.get_client(expiration_time=AZ_CACHE_SECONDS)

    return MC


def reset_cache():
    """Reset the cache, mainly for testing purposes and update
    availability_zone for host aggregate
    """

    global MC

    MC = None


def _make_cache_key(host):
    return "azcache-%s" % host


def _build_metadata_by_host(aggregates, hosts=None):
    if hosts and not isinstance(hosts, set):
        hosts = set(hosts)
    metadata = collections.defaultdict(set)
    for aggregate in aggregates:
        for host in aggregate.hosts:
            if hosts and host not in hosts:
                continue
            metadata[host].add(list(aggregate.metadata.values())[0])
    return metadata


def set_availability_zones(context, services):
    # Makes sure services isn't a sqlalchemy object
    services = [dict(service) for service in services]
    hosts = set([service['host'] for service in services])
    aggregates = objects.AggregateList.get_by_metadata_key(context,
            'availability_zone', hosts=hosts)
    metadata = _build_metadata_by_host(aggregates, hosts=hosts)
    # gather all of the availability zones associated with a service host
    for service in services:
        az = CONF.internal_service_availability_zone
        if service['topic'] == "compute":
            if metadata.get(service['host']):
                az = u','.join(list(metadata[service['host']]))
            else:
                az = CONF.default_availability_zone
                # update the cache
                update_host_availability_zone_cache(context,
                                                    service['host'], az)
        service['availability_zone'] = az
    return services


def get_host_availability_zone(context, host):
    aggregates = objects.AggregateList.get_by_host(context, host,
                                                   key='availability_zone')
    if aggregates:
        az = aggregates[0].metadata['availability_zone']
    else:
        az = CONF.default_availability_zone
    return az


def update_host_availability_zone_cache(context, host, availability_zone=None):
    if not availability_zone:
        availability_zone = get_host_availability_zone(context, host)
    cache = _get_cache()
    cache_key = _make_cache_key(host)
    cache.delete(cache_key)
    cache.set(cache_key, availability_zone)


def get_availability_zones(context, hostapi, get_only_available=False,
                           with_hosts=False, services=None):
    """Return available and unavailable zones on demand.

    :param context: nova auth RequestContext
    :param hostapi: nova.compute.api.HostAPI instance
    :param get_only_available: flag to determine whether to return
        available zones only, default False indicates return both
        available zones and not available zones, True indicates return
        available zones only
    :param with_hosts: whether to return hosts part of the AZs
    :type with_hosts: bool
    :param services: list of services to use; if None, enabled services will be
        retrieved from all cells with zones set
    """
    if services is None:
        services = hostapi.service_get_all(
            context, set_zones=True, all_cells=True)

    enabled_services = []
    disabled_services = []
    for service in services:
        if not service.disabled:
            enabled_services.append(service)
        else:
            disabled_services.append(service)

    if with_hosts:
        return _get_availability_zones_with_hosts(
            enabled_services, disabled_services, get_only_available)
    else:
        return _get_availability_zones(
            enabled_services, disabled_services, get_only_available)


def _get_availability_zones(
        enabled_services, disabled_services, get_only_available=False):

    available_zones = {
        service['availability_zone'] for service in enabled_services
    }

    if get_only_available:
        return sorted(available_zones)

    not_available_zones = {
        service['availability_zone'] for service in disabled_services
        if service['availability_zone'] not in available_zones
    }

    return sorted(available_zones), sorted(not_available_zones)


def _get_availability_zones_with_hosts(
        enabled_services, disabled_services, get_only_available=False):

    available_zones = collections.defaultdict(set)
    for service in enabled_services:
        available_zones[service['availability_zone']].add(service['host'])

    if get_only_available:
        return sorted(available_zones.items())

    not_available_zones = collections.defaultdict(set)
    for service in disabled_services:
        if service['availability_zone'] in available_zones:
            continue

        not_available_zones[service['availability_zone']].add(service['host'])

    return sorted(available_zones.items()), sorted(not_available_zones.items())


def get_instance_availability_zone(context, instance):
    """Return availability zone of specified instance."""
    host = instance.host if 'host' in instance else None
    if not host:
        # Likely hasn't reached a viable compute node yet so give back the
        # desired availability_zone in the instance record if the boot request
        # specified one.
        az = instance.get('availability_zone')
        return az

    cache_key = _make_cache_key(host)
    cache = _get_cache()
    az = cache.get(cache_key)
    az_inst = instance.get('availability_zone')
    if az_inst is not None and az != az_inst:
        # NOTE(sbauza): Cache is wrong, we need to invalidate it by fetching
        # again the right AZ related to the aggregate the host belongs to.
        # As the API is also calling this method for setting the instance
        # AZ field, we don't need to update the instance.az field.
        # This case can happen because the cache is populated before the
        # instance has been assigned to the host so that it would keep the
        # former reference which was incorrect. Instead of just taking the
        # instance AZ information for refilling the cache, we prefer to
        # invalidate the cache and fetch it again because there could be some
        # corner cases where this method could be called before the instance
        # has been assigned to the host also.
        az = None
    if not az:
        elevated = context.elevated()
        az = get_host_availability_zone(elevated, host)
        cache.set(cache_key, az)
    return az
