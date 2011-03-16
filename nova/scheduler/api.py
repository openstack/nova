# Copyright (c) 2011 Openstack, LLC.
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

"""
Handles all requests relating to schedulers.
"""

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.scheduler.api')


def _call_scheduler(method, context, params=None):
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


class API(object):
    """API for interacting with the scheduler."""

    @classmethod
    def _is_current_zone(cls, zone):
        return True

    @classmethod
    def get_zone_list(cls, context):
        """Return a list of zones assoicated with this zone."""
        items = _call_scheduler('get_zone_list', context)
        for item in items:
            item['api_url'] = item['api_url'].replace('\\/', '/')
        return items

    @classmethod
    def get_zone_capabilities(cls, context, service=None):
        """Returns a dict of key, value capabilities for this zone,
           or for a particular class of services running in this zone."""
        return _call_scheduler('get_zone_capabilities', context=context,
                            params=dict(service=service))

    @classmethod
    def update_service_capabilities(cls, context, service_name, host,
                                                capabilities):
        """Send an update to all the scheduler services informing them
           of the capabilities of this service."""
        kwargs = dict(method='update_service_capabilities',
                      args=dict(service_name=service_name, host=host,
                                capabilities=capabilities))
        return rpc.fanout_cast(context, 'scheduler', kwargs)
        
    @classmethod
    def get_instance_or_reroute(cls, context, instance_id):
        instance = db.instance_get(context, instance_id)
        zones = db.zone_get_all(context)

        LOG.debug("*** Firing ZoneRouteException")
        # Throw a reroute Exception for the middleware to pick up. 
        raise exception.ZoneRouteException(zones)

    @classmethod
    def get_queue_for_instance(cls, context, service, instance_id):
        instance = db.instance_get(context, instance_id)
        zone = db.get_zone(instance.zone.id)
        if cls._is_current_zone(zone):
            return db.queue_get_for(context, service, instance['host'])

        # Throw a reroute Exception for the middleware to pick up. 
        raise exception.ZoneRouteException(zone)
