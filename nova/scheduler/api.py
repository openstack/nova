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

from novaclient import v1_1 as novaclient
from novaclient import exceptions as novaclient_exceptions

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova import utils

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


def get_host_list(context):
    """Return a list of hosts associated with this zone."""
    return _call_scheduler('get_host_list', context)


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
            params={"request_spec": specs})


def update_service_capabilities(context, service_name, host, capabilities):
    """Send an update to all the scheduler services informing them
       of the capabilities of this service."""
    kwargs = dict(method='update_service_capabilities',
                  args=dict(service_name=service_name, host=host,
                            capabilities=capabilities))
    return rpc.fanout_cast(context, 'scheduler', kwargs)


def call_zone_method(context, method_name, errors_to_ignore=None,
                     novaclient_collection_name='zones', zones=None,
                     *args, **kwargs):
    """Returns a list of (zone, call_result) objects."""
    if not isinstance(errors_to_ignore, (list, tuple)):
        # This will also handle the default None
        errors_to_ignore = [errors_to_ignore]

    pool = greenpool.GreenPool()
    results = []
    if zones is None:
        zones = db.zone_get_all(context)
    for zone in zones:
        try:
            nova = novaclient.Client(zone.username, zone.password, None,
                    zone.api_url)
            nova.authenticate()
        except novaclient_exceptions.BadRequest, e:
            url = zone.api_url
            LOG.warn(_("Failed request to zone; URL=%(url)s: %(e)s")
                    % locals())
            #TODO (dabo) - add logic for failure counts per zone,
            # with escalation after a given number of failures.
            continue
        novaclient_collection = getattr(nova, novaclient_collection_name)
        collection_method = getattr(novaclient_collection, method_name)

        def _error_trap(*args, **kwargs):
            try:
                return collection_method(*args, **kwargs)
            except Exception as e:
                if type(e) in errors_to_ignore:
                    return None
                raise

        res = pool.spawn(_error_trap, *args, **kwargs)
        results.append((zone, res))
    pool.waitall()
    return [(zone.id, res.wait()) for zone, res in results]


def child_zone_helper(zone_list, func):
    """Fire off a command to each zone in the list.
    The return is [novaclient return objects] from each child zone.
    For example, if you are calling server.pause(), the list will
    be whatever the response from server.pause() is. One entry
    per child zone called."""

    def _wrap_method(function, arg1):
        """Wrap method to supply an argument."""
        def _wrap(*args, **kwargs):
            return function(arg1, *args, **kwargs)
        return _wrap

    def _process(func, zone):
        """Worker stub for green thread pool. Give the worker
        an authenticated nova client and zone info."""
        try:
            nova = novaclient.Client(zone.username, zone.password, None,
                    zone.api_url)
            nova.authenticate()
        except novaclient_exceptions.BadRequest, e:
            url = zone.api_url
            LOG.warn(_("Failed request to zone; URL=%(url)s: %(e)s")
                    % locals())
            # This is being returned instead of raised, so that when
            # results are processed in unmarshal_result() after the
            # greenpool.imap completes, the exception can be raised
            # there if no other zones had a response.
            return exception.ZoneRequestError()
        else:
            return func(nova, zone)

    green_pool = greenpool.GreenPool()
    return [result for result in green_pool.imap(
                    _wrap_method(_process, func), zone_list)]


def _issue_novaclient_command(nova, zone, collection,
        method_name, *args, **kwargs):
    """Use novaclient to issue command to a single child zone.
       One of these will be run in parallel for each child zone.
    """
    manager = getattr(nova, collection)

    # NOTE(comstud): This is not ideal, but we have to do this based on
    # how novaclient is implemented right now.
    # 'find' is special cased as novaclient requires kwargs for it to
    # filter on a 'get_all'.
    # Every other method first needs to do a 'get' on the first argument
    # passed, which should be a UUID.  If it's 'get' itself that we want,
    # we just return the result.  Otherwise, we next call the real method
    # that's wanted... passing other arguments that may or may not exist.
    if method_name in ['find', 'findall']:
        try:
            return getattr(manager, method_name)(**kwargs)
        except novaclient_exceptions.NotFound:
            url = zone.api_url
            LOG.debug(_("%(collection)s.%(method_name)s didn't find "
                    "anything matching '%(kwargs)s' on '%(url)s'" %
                    locals()))
            return None

    args = list(args)
    # pop off the UUID to look up
    item = args.pop(0)
    try:
        result = manager.get(item)
    except novaclient_exceptions.NotFound:
        url = zone.api_url
        LOG.debug(_("%(collection)s '%(item)s' not found on '%(url)s'" %
                                                locals()))
        return None

    if method_name.lower() != 'get':
        # if we're doing something other than 'get', call it passing args.
        result = getattr(result, method_name)(*args, **kwargs)
    return result


def wrap_novaclient_function(f, collection, method_name, *args, **kwargs):
    """Appends collection, method_name and arguments to the incoming
    (nova, zone) call from child_zone_helper."""
    def inner(nova, zone):
        return f(nova, zone, collection, method_name, *args, **kwargs)

    return inner


class RedirectResult(exception.Error):
    """Used to the HTTP API know that these results are pre-cooked
    and they can be returned to the caller directly."""
    def __init__(self, results):
        self.results = results
        super(RedirectResult, self).__init__(
               message=_("Uncaught Zone redirection exception"))


class reroute_compute(object):
    """
    reroute_compute is responsible for trying to lookup a resource in the
    current zone and if it's not found there, delegating the call to the
    child zones.

    Since reroute_compute will be making 'cross-zone' calls, the ID for the
    object must come in as a UUID-- if we receive an integer ID, we bail.

    The steps involved are:

        1. Validate that item_id is UUID like

        2. Lookup item by UUID in the zone local database

        3. If the item was found, then extract integer ID, and pass that to
           the wrapped method. (This ensures that zone-local code can
           continue to use integer IDs).

        4. If the item was not found, we delegate the call to a child zone
           using the UUID.
    """
    def __init__(self, method_name):
        self.method_name = method_name

    def _route_to_child_zones(self, context, collection, item_uuid):
        if not FLAGS.enable_zone_routing:
            raise exception.InstanceNotFound(instance_id=item_uuid)

        self.item_uuid = item_uuid

        zones = db.zone_get_all(context)
        if not zones:
            raise exception.InstanceNotFound(instance_id=item_uuid)

        # Ask the children to provide an answer ...
        LOG.debug(_("Asking child zones ..."))
        result = self._call_child_zones(zones,
                    wrap_novaclient_function(_issue_novaclient_command,
                           collection, self.method_name, item_uuid))
        # Scrub the results and raise another exception
        # so the API layers can bail out gracefully ...
        raise RedirectResult(self.unmarshall_result(result))

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            collection, context, item_id_or_uuid = \
                            self.get_collection_context_and_id(args, kwargs)

            attempt_reroute = False
            if utils.is_uuid_like(item_id_or_uuid):
                item_uuid = item_id_or_uuid
                try:
                    instance = db.instance_get_by_uuid(context, item_uuid)
                except exception.InstanceNotFound, e:
                    # NOTE(sirp): since a UUID was passed in, we can attempt
                    # to reroute to a child zone
                    attempt_reroute = True
                    LOG.debug(_("Instance %(item_uuid)s not found "
                                        "locally: '%(e)s'" % locals()))
                else:
                    # NOTE(sirp): since we're not re-routing in this case, and
                    # we we were passed a UUID, we need to replace that UUID
                    # with an integer ID in the argument list so that the
                    # zone-local code can continue to use integer IDs.
                    item_id = instance['id']
                    args = list(args)      # needs to be mutable to replace
                    self.replace_uuid_with_id(args, kwargs, item_id)

            if attempt_reroute:
                return self._route_to_child_zones(context, collection,
                        item_uuid)
            else:
                return f(*args, **kwargs)

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

    @staticmethod
    def replace_uuid_with_id(args, kwargs, replacement_id):
        """
        Extracts the UUID parameter from the arg or kwarg list and replaces
        it with an integer ID.
        """
        if 'instance_id' in kwargs:
            kwargs['instance_id'] = replacement_id
        elif len(args) > 1:
            args.pop(2)
            args.insert(2, replacement_id)

    def unmarshall_result(self, zone_responses):
        """Result is a list of responses from each child zone.
        Each decorator derivation is responsible to turning this
        into a format expected by the calling method. For
        example, this one is expected to return a single Server
        dict {'server':{k:v}}. Others may return a list of them, like
        {'servers':[{k,v}]}"""
        reduced_response = []
        found_exception = None
        for zone_response in zone_responses:
            if not zone_response:
                continue
            if isinstance(zone_response, BaseException):
                found_exception = zone_response
                continue

            server = zone_response.__dict__

            for k in server.keys():
                if k[0] == '_' or k == 'manager':
                    del server[k]

            reduced_response.append(dict(server=server))
        if reduced_response:
            return reduced_response[0]  # first for now.
        elif found_exception:
            raise found_exception
        raise exception.InstanceNotFound(instance_id=self.item_uuid)


def redirect_handler(f):
    def new_f(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except RedirectResult, e:
            return e.results
    return new_f
