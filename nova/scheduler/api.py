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

import novaclient

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc

from eventlet import greenpool

FLAGS = flags.FLAGS
flags.DEFINE_bool('enable_zone_routing',
    False,
    'When True, routing to child zones will occur.')

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
    """Wrap method to supply self."""
    def _wrap(*args, **kwargs):
        return function(self, *args, **kwargs)
    return _wrap


def _process(func, zone):
    """Worker stub for green thread pool. Give the worker
    an authenticated nova client and zone info."""
    nova = novaclient.OpenStack(zone.username, zone.password, zone.api_url)
    nova.authenticate()
    return func(nova, zone)


def child_zone_helper(zone_list, func):
    """Fire off a command to each zone in the list."""
    green_pool = greenpool.GreenPool()
    return [result for result in green_pool.imap(
                    _wrap_method(_process, func), zone_list)]


def _issue_novaclient_command(nova, zone, collection, method_name, \
                                                        item_id):
    """Use novaclient to issue command to a single child zone.
       One of these will be run in parallel for each child zone."""
    item = None
    try:
        manager = getattr(nova, collection)
        if isinstance(item_id, int) or item_id.isdigit():
            item = manager.get(int(item_id))
        else:
            item = manager.find(name=item_id)
    except novaclient.NotFound:
        url = zone.api_url
        LOG.debug(_("%(collection)s '%(item_id)s' not found on '%(url)s'" %
                                                locals()))
        return

    LOG.debug("***CALLING CHILD ZONE")
    result = getattr(item, method_name)()
    LOG.debug("***CHILD ZONE GAVE %s", result)
    return result


def wrap_novaclient_function(f, collection, method_name, item_id):
    """Appends collection, method_name and item_id to the incoming
    (nova, zone) call from child_zone_helper."""
    def inner(nova, zone):
        return f(nova, zone, collection, method_name, item_id)
        
    return inner


class reroute_compute(object):
    """Decorator used to indicate that the method should
       delegate the call the child zones if the db query
       can't find anything."""
    def __init__(self, method_name):
        self.method_name = method_name

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            collection, context, item_id = \
                            self.get_collection_context_and_id(args)
            try:
                return f(*args, **kwargs)
            except exception.InstanceNotFound, e:
                LOG.debug(_("Instance %(item_id)s not found "
                                    "locally: '%(e)s'" % locals()))

                if not FLAGS.enable_zone_routing:
                    raise
                    
                zones = db.zone_get_all(context)
                if not zones:
                    raise

                result = child_zone_helper(zones,
                            wrap_novaclient_function(_issue_novaclient_command,
                                   collection, self.method_name, item_id))
                LOG.debug("***REROUTE: %s" % result)
                return self.unmarshall_result(result)
        return wrapped_f

    def get_collection_context_and_id(self, args):
        """Returns a tuple of (novaclient collection name, security
           context and resource id. Derived class should override this."""
        return ("servers", args[1], args[2])

    def unmarshall_result(self, result):
        return result        
