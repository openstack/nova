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

import novaclient.client as client

from eventlet import greenpool

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


def _wrap_method(function, self):
    """Wrap method to supply 'self'."""
    def _wrap(*args, **kwargs):
        return function(self, *args, **kwargs)
    return _wrap


def _process(self, zone):
    """Worker stub for green thread pool"""
    nova = client.OpenStackClient(zone.username, zone.password,
                                        zone.api_url)
    nova.authenticate()
    return self.process(nova, zone)


class ChildZoneHelper(object):
    """Delegate a call to a set of Child Zones and wait for their
       responses. Could be used for Zone Redirect or by the Scheduler
       plug-ins to query the children."""

    def start(self, zone_list):
        """Spawn a green thread for each child zone, calling the
        derived classes process() method as the worker. Returns
        a list of HTTP Responses. 1 per child."""
        self.green_pool = greenpool.GreenPool()
        return [result for result in self.green_pool.imap(
                        _wrap_method(_process, self), zone_list)]

    def process(self, client, zone):
        """Worker Method. Derived class must override."""
        pass
