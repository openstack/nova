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


def _process(func, zone):
    """Worker stub for green thread pool"""
    nova = client.OpenStackClient(zone.username, zone.password,
                                        zone.api_url)
    nova.authenticate()
    return func(nova, zone)


def child_zone_helper(zone_list, func):
    green_pool = greenpool.GreenPool()
    return [result for result in green_pool.imap(
                    _wrap_method(_process, func), zone_list)]


def _issue_novaclient_command(nova, zone, method_name, instance_id):
    server = None
    try:
        if isinstance(instance_id, int) or instance_id.isdigit():
            server = manager.get(int(instance_id))
        else:
            server = manager.find(name=instance_id)
    except novaclient.NotFound:
        url = zone.api_url
        LOG.debug(_("Instance %(instance_id)s not found on '%(url)s'" %
                                                locals()))
        return

    return getattr(server, method_name)()


def wrap_novaclient_function(f, method_name, instance_id):
    def inner(nova, zone):
        return f(nova, zone, method_name, instance_id)
        
    return inner


class reroute_if_not_found(object):
    """Decorator used to indicate that the method should
       delegate the call the child zones if the db query
       can't find anything.
    """
    def __init__(self, method_name):
        self.method_name = method_name

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            LOG.debug("***REROUTE-3: %s / %s" % (args, kwargs))
            context = args[1]
            instance_id = args[2]
            try:
                return f(*args, **kwargs)
            except exception.InstanceNotFound, e:
                LOG.debug(_("Instance %(instance_id)s not found "
                                    "locally: '%(e)s'" % locals()))

                zones = db.zone_get_all(context)
                result = child_zone_helper(zones,
                            wrap_novaclient_function(_issue_novaclient_command,
                                   self.method_name, instance_id))
                LOG.debug("***REROUTE: %s" % result)
                return result
        return wrapped_f
