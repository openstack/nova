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
      - Optionally json_body is decoded to provide all the parameters.
    - Actual work is done and a result is returned.
    - That result is turned into json and returned.

"""

import urllib

import routes
import webob

from nova import context
from nova import flags
from nova import utils
from nova import wsgi


EASY_ROUTES = {}


def register_service(path, handle):
    EASY_ROUTES[path] = handle


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


class ReqParamsMiddleware(wsgi.Middleware):
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


class SundayMorning(wsgi.Router):
    def __init__(self, mapper=None):
        if mapper is None:
            mapper = routes.Mapper()
        
        self._load_registered_routes(mapper)
        super(SundayMorning, self).__init__(mapper=mapper)

    def _load_registered_routes(self, mapper):
        for route in EASY_ROUTES:
            mapper.connect('/%s/{action}' % route,
                           controller=ServiceWrapper(EASY_ROUTES[route]))


class ServiceWrapper(wsgi.Controller):
    def __init__(self, service_handle):
        self.service_handle = service_handle
    
    @webob.dec.wsgify
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
        
        result = method(context, **params)
        if type(result) is dict or type(result) is list:
            return self._serialize(result, req)
        else:
            return result


class Proxy(object):
    """Pretend an Easy API endpoint is an object."""
    def __init__(self, app, prefix=None):
        self.app = app
        self.prefix = prefix
    
    def __do_request(self, path, context, **kwargs):
        req = webob.Request.blank(path)
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
            return self.__class__(self.app, key)
        
        def _wrapper(context, **kwargs):
            return self.__do_request('/%s/%s' % (self.prefix, key),
                                     context,
                                     **kwargs)
        _wrapper.func_name = key
        return _wrapper



