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


def get_zone_list(context):
    """Return a list of zones assoicated with this zone."""
    items = _call_scheduler('get_zone_list', context)
    for item in items:
        item['api_url'] = item['api_url'].replace('\\/', '/')
    if not items:
        items = db.zone_get_all(context)
    return items


def zone_get(context, zone_id):
    return db.zone_get(context, zone_id)


def zone_delete(context, zone_id):
    return db.zone_delete(context, zone_id)


def zone_create(context, data):
    return db.zone_create(context, data)


def zone_update(context, zone_id, data):
    return db.zone_update(context, zone_id, data)


def get_zone_capabilities(context):
    """Returns a dict of key, value capabilities for this zone."""
    return _call_scheduler('get_zone_capabilities', context=context)


def select(context, specs=None):
    """Returns a list of hosts."""
    return _call_scheduler('select', context=context,
            params={"specs": specs})


def update_service_capabilities(context, service_name, host, capabilities):
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
    """Fire off a command to each zone in the list.
    The return is [novaclient return objects] from each child zone.
    For example, if you are calling server.pause(), the list will
    be whatever the response from server.pause() is. One entry
    per child zone called."""
    green_pool = greenpool.GreenPool()
    return [result for result in green_pool.imap(
                    _wrap_method(_process, func), zone_list)]


def _issue_novaclient_command(nova, zone, collection, method_name, item_id):
    """Use novaclient to issue command to a single child zone.
       One of these will be run in parallel for each child zone."""
    manager = getattr(nova, collection)
    result = None
    try:
        try:
            result = manager.get(int(item_id))
        except ValueError, e:
            result = manager.find(name=item_id)
    except novaclient.NotFound:
        url = zone.api_url
        LOG.debug(_("%(collection)s '%(item_id)s' not found on '%(url)s'" %
                                                locals()))
        return None

    if method_name.lower() not in ['get', 'find']:
        result = getattr(result, method_name)()
    return result


def wrap_novaclient_function(f, collection, method_name, item_id):
    """Appends collection, method_name and item_id to the incoming
    (nova, zone) call from child_zone_helper."""
    def inner(nova, zone):
        return f(nova, zone, collection, method_name, item_id)

    return inner


class RedirectResult(exception.Error):
    """Used to the HTTP API know that these results are pre-cooked
    and they can be returned to the caller directly."""
    def __init__(self, results):
        self.results = results
        super(RedirectResult, self).__init__(
               message=_("Uncaught Zone redirection exception"))


class reroute_compute(object):
    """Decorator used to indicate that the method should
       delegate the call the child zones if the db query
       can't find anything."""
    def __init__(self, method_name):
        self.method_name = method_name

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            collection, context, item_id = \
                            self.get_collection_context_and_id(args, kwargs)
            try:
                # Call the original function ...
                return f(*args, **kwargs)
            except exception.InstanceNotFound, e:
                LOG.debug(_("Instance %(item_id)s not found "
                                    "locally: '%(e)s'" % locals()))

                if not FLAGS.enable_zone_routing:
                    raise

                zones = db.zone_get_all(context)
                if not zones:
                    raise

                # Ask the children to provide an answer ...
                LOG.debug(_("Asking child zones ..."))
                result = self._call_child_zones(zones,
                            wrap_novaclient_function(_issue_novaclient_command,
                                   collection, self.method_name, item_id))
                # Scrub the results and raise another exception
                # so the API layers can bail out gracefully ...
                raise RedirectResult(self.unmarshall_result(result))
        return wrapped_f

    def _call_child_zones(self, zones, function):
        """Ask the child zones to perform this operation.
        Broken out for testing."""
        return child_zone_helper(zones, function)

    def get_collection_context_and_id(self, args, kwargs):
        """Returns a tuple of (novaclient collection name, security
           context and resource id. Derived class should override this."""
        context = kwargs.get('context', None)
        instance_id = kwargs.get('instance_id', None)
        if len(args) > 0 and not context:
            context = args[1]
        if len(args) > 1 and not instance_id:
            instance_id = args[2]
        return ("servers", context, instance_id)

    def unmarshall_result(self, zone_responses):
        """Result is a list of responses from each child zone.
        Each decorator derivation is responsible to turning this
        into a format expected by the calling method. For
        example, this one is expected to return a single Server
        dict {'server':{k:v}}. Others may return a list of them, like
        {'servers':[{k,v}]}"""
        reduced_response = []
        for zone_response in zone_responses:
            if not zone_response:
                continue

            server = zone_response.__dict__

            for k in server.keys():
                if k[0] == '_' or k == 'manager':
                    del server[k]

            reduced_response.append(dict(server=server))
        if reduced_response:
            return reduced_response[0]  # first for now.
        return {}


def redirect_handler(f):
    def new_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except RedirectResult, e:
            return e.results
    return new_f
