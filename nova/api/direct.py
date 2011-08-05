# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Public HTTP interface that allows services to self-register.

The general flow of a request is:
    - Request is parsed into WSGI bits.
    - Some middleware checks authentication.
    - Routing takes place based on the URL to find a controller.
      (/controller/method)
    - Parameters are parsed from the request and passed to a method on the
      controller as keyword arguments.
      - Optionally 'json' is decoded to provide all the parameters.
    - Actual work is done and a result is returned.
    - That result is turned into json and returned.

"""

import inspect
import urllib

import routes
import webob

from nova import context
from nova import exception
from nova import flags
from nova import utils
from nova import wsgi
import nova.api.openstack.wsgi


# Global storage for registering modules.
ROUTES = {}


def register_service(path, handle):
    """Register a service handle at a given path.

    Services registered in this way will be made available to any instances of
    nova.api.direct.Router.

    :param path: `routes` path, can be a basic string like "/path"
    :param handle: an object whose methods will be made available via the api

    """
    ROUTES[path] = handle


class Router(wsgi.Router):
    """A simple WSGI router configured via `register_service`.

    This is a quick way to attach multiple services to a given endpoint.
    It will automatically load the routes registered in the `ROUTES` global.

    TODO(termie): provide a paste-deploy version of this.

    """

    def __init__(self, mapper=None):
        if mapper is None:
            mapper = routes.Mapper()

        self._load_registered_routes(mapper)
        super(Router, self).__init__(mapper=mapper)

    def _load_registered_routes(self, mapper):
        for route in ROUTES:
            mapper.connect('/%s/{action}' % route,
                           controller=ServiceWrapper(ROUTES[route]))


class DelegatedAuthMiddleware(wsgi.Middleware):
    """A simple and naive authentication middleware.

    Designed mostly to provide basic support for alternative authentication
    schemes, this middleware only desires the identity of the user and will
    generate the appropriate nova.context.RequestContext for the rest of the
    application. This allows any middleware above it in the stack to
    authenticate however it would like while only needing to conform to a
    minimal interface.

    Expects two headers to determine identity:
     - X-OpenStack-User
     - X-OpenStack-Project

    This middleware is tied to identity management and will need to be kept
    in sync with any changes to the way identity is dealt with internally.

    """

    def process_request(self, request):
        os_user = request.headers['X-OpenStack-User']
        os_project = request.headers['X-OpenStack-Project']
        context_ref = context.RequestContext(user_id=os_user,
                                             project_id=os_project)
        request.environ['openstack.context'] = context_ref


class JsonParamsMiddleware(wsgi.Middleware):
    """Middleware to allow method arguments to be passed as serialized JSON.

    Accepting arguments as JSON is useful for accepting data that may be more
    complex than simple primitives.

    In this case we accept it as urlencoded data under the key 'json' as in
    json=<urlencoded_json> but this could be extended to accept raw JSON
    in the POST body.

    Filters out the parameters `self`, `context` and anything beginning with
    an underscore.

    """

    def process_request(self, request):
        if 'json' not in request.params:
            return

        params_json = request.params['json']
        params_parsed = utils.loads(params_json)
        params = {}
        for k, v in params_parsed.iteritems():
            if k in ('self', 'context'):
                continue
            if k.startswith('_'):
                continue
            params[k] = v

        request.environ['openstack.params'] = params


class PostParamsMiddleware(wsgi.Middleware):
    """Middleware to allow method arguments to be passed as POST parameters.

    Filters out the parameters `self`, `context` and anything beginning with
    an underscore.

    """

    def process_request(self, request):
        params_parsed = request.params
        params = {}
        for k, v in params_parsed.iteritems():
            if k in ('self', 'context'):
                continue
            if k.startswith('_'):
                continue
            params[k] = v

        request.environ['openstack.params'] = params


class Reflection(object):
    """Reflection methods to list available methods.

    This is an object that expects to be registered via register_service.
    These methods allow the endpoint to be self-describing. They introspect
    the exposed methods and provide call signatures and documentation for
    them allowing quick experimentation.

    """

    def __init__(self):
        self._methods = {}
        self._controllers = {}

    def _gather_methods(self):
        """Introspect available methods and generate documentation for them."""
        methods = {}
        controllers = {}
        for route, handler in ROUTES.iteritems():
            controllers[route] = handler.__doc__.split('\n')[0]
            for k in dir(handler):
                if k.startswith('_'):
                    continue
                f = getattr(handler, k)
                if not callable(f):
                    continue

                # bunch of ugly formatting stuff
                argspec = inspect.getargspec(f)
                args = [x for x in argspec[0]
                        if x != 'self' and x != 'context']
                defaults = argspec[3] and argspec[3] or []
                args_r = list(reversed(args))
                defaults_r = list(reversed(defaults))

                args_out = []
                while args_r:
                    if defaults_r:
                        args_out.append((args_r.pop(0),
                                         repr(defaults_r.pop(0))))
                    else:
                        args_out.append((str(args_r.pop(0)),))

                # if the method accepts keywords
                if argspec[2]:
                    args_out.insert(0, ('**%s' % argspec[2],))

                if f.__doc__:
                    short_doc = f.__doc__.split('\n')[0]
                    doc = f.__doc__
                else:
                    short_doc = doc = _('not available')

                methods['/%s/%s' % (route, k)] = {
                        'short_doc': short_doc,
                        'doc': doc,
                        'name': k,
                        'args': list(reversed(args_out))}

        self._methods = methods
        self._controllers = controllers

    def get_controllers(self, context):
        """List available controllers."""
        if not self._controllers:
            self._gather_methods()

        return self._controllers

    def get_methods(self, context):
        """List available methods."""
        if not self._methods:
            self._gather_methods()

        method_list = self._methods.keys()
        method_list.sort()
        methods = {}
        for k in method_list:
            methods[k] = self._methods[k]['short_doc']
        return methods

    def get_method_info(self, context, method):
        """Get detailed information about a method."""
        if not self._methods:
            self._gather_methods()
        return self._methods[method]


class ServiceWrapper(object):
    """Wrapper to dynamically povide a WSGI controller for arbitrary objects.

    With lightweight introspection allows public methods on the object to
    be accesed via simple WSGI routing and parameters and serializes the
    return values.

    Automatically used be nova.api.direct.Router to wrap registered instances.

    """

    def __init__(self, service_handle):
        self.service_handle = service_handle

    @webob.dec.wsgify(RequestClass=nova.api.openstack.wsgi.Request)
    def __call__(self, req):
        arg_dict = req.environ['wsgiorg.routing_args'][1]
        action = arg_dict['action']
        del arg_dict['action']

        context = req.environ['openstack.context']
        # allow middleware up the stack to override the params
        params = {}
        if 'openstack.params' in req.environ:
            params = req.environ['openstack.params']

        # TODO(termie): do some basic normalization on methods
        method = getattr(self.service_handle, action)

        # NOTE(vish): make sure we have no unicode keys for py2.6.
        params = dict([(str(k), v) for (k, v) in params.iteritems()])
        result = method(context, **params)

        if result is None or type(result) is str or type(result) is unicode:
            return result

        try:
            content_type = req.best_match_content_type()
            serializer = {
              'application/xml': nova.api.openstack.wsgi.XMLDictSerializer(),
              'application/json': nova.api.openstack.wsgi.JSONDictSerializer(),
            }[content_type]
            return serializer.serialize(result)
        except Exception, e:
            raise exception.Error(_("Returned non-serializable type: %s")
                                  % result)


class Limited(object):
    __notdoc = """Limit the available methods on a given object.

    (Not a docstring so that the docstring can be conditionally overriden.)

    Useful when defining a public API that only exposes a subset of an
    internal API.

    Expected usage of this class is to define a subclass that lists the allowed
    methods in the 'allowed' variable.

    Additionally where appropriate methods can be added or overwritten, for
    example to provide backwards compatibility.

    The wrapping approach has been chosen so that the wrapped API can maintain
    its own internal consistency, for example if it calls "self.create" it
    should get its own create method rather than anything we do here.

    """

    _allowed = None

    def __init__(self, proxy):
        self._proxy = proxy
        if not self.__doc__:  # pylint: disable=E0203
            self.__doc__ = proxy.__doc__
        if not self._allowed:
            self._allowed = []

    def __getattr__(self, key):
        """Only return methods that are named in self._allowed."""
        if key not in self._allowed:
            raise AttributeError()
        return getattr(self._proxy, key)

    def __dir__(self):
        """Only return methods that are named in self._allowed."""
        return [x for x in dir(self._proxy) if x in self._allowed]


class Proxy(object):
    """Pretend a Direct API endpoint is an object.

    This is mostly useful in testing at the moment though it should be easily
    extendable to provide a basic API library functionality.

    In testing we use this to stub out internal objects to verify that results
    from the API are serializable.

    """

    def __init__(self, app, prefix=None):
        self.app = app
        self.prefix = prefix

    def __do_request(self, path, context, **kwargs):
        req = wsgi.Request.blank(path)
        req.method = 'POST'
        req.body = urllib.urlencode({'json': utils.dumps(kwargs)})
        req.environ['openstack.context'] = context
        resp = req.get_response(self.app)
        try:
            return utils.loads(resp.body)
        except Exception:
            return resp.body

    def __getattr__(self, key):
        if self.prefix is None:
            return self.__class__(self.app, prefix=key)

        def _wrapper(context, **kwargs):
            return self.__do_request('/%s/%s' % (self.prefix, key),
                                     context,
                                     **kwargs)
        _wrapper.func_name = key
        return _wrapper
