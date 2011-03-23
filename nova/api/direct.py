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
from nova import flags
from nova import utils
from nova import wsgi


ROUTES = {}


def register_service(path, handle):
    ROUTES[path] = handle


class Router(wsgi.Router):
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
    def process_request(self, request):
        os_user = request.headers['X-OpenStack-User']
        os_project = request.headers['X-OpenStack-Project']
        context_ref = context.RequestContext(user=os_user, project=os_project)
        request.environ['openstack.context'] = context_ref


class JsonParamsMiddleware(wsgi.Middleware):
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
    """Reflection methods to list available methods."""
    def __init__(self):
        self._methods = {}
        self._controllers = {}

    def _gather_methods(self):
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


class ServiceWrapper(wsgi.Controller):
    def __init__(self, service_handle):
        self.service_handle = service_handle

    @webob.dec.wsgify(RequestClass=wsgi.Request)
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
        if type(result) is dict or type(result) is list:
            content_type = req.best_match_content_type()
            default_xmlns = self.get_default_xmlns(req)
            return self._serialize(result, content_type, default_xmlns)
        else:
            return result


class Proxy(object):
    """Pretend a Direct API endpoint is an object."""
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
