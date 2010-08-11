# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 OpenStack LLC.
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
Utility methods for working with WSGI servers
"""

import logging
import sys

import eventlet
import eventlet.wsgi
eventlet.patcher.monkey_patch(all=False, socket=True)
import routes
import routes.middleware
import webob.dec
import webob.exc


logging.getLogger("routes.middleware").addHandler(logging.StreamHandler())


def run_server(application, port):
    """Run a WSGI server with the given application."""
    sock = eventlet.listen(('0.0.0.0', port))
    eventlet.wsgi.server(sock, application)


# TODO(gundlach): I think we should toss this class, now that it has no purpose.
class Application(object):
    """Base WSGI application wrapper. Subclasses need to implement __call__."""

    def __call__(self, environ, start_response):
        r"""Subclasses will probably want to implement __call__ like this:

        @webob.dec.wsgify
        def __call__(self, req):
          # Any of the following objects work as responses:

          # Option 1: simple string
          res = 'message\n'

          # Option 2: a nicely formatted HTTP exception page
          res = exc.HTTPForbidden(detail='Nice try')

          # Option 3: a webob Response object (in case you need to play with
          # headers, or you want to be treated like an iterable, or or or)
          res = Response();
          res.app_iter = open('somefile')

          # Option 4: any wsgi app to be run next
          res = self.application

          # Option 5: you can get a Response object for a wsgi app, too, to
          # play with headers etc
          res = req.get_response(self.application)

          # You can then just return your response...
          return res
          # ... or set req.response and return None.
          req.response = res

        See the end of http://pythonpaste.org/webob/modules/dec.html
        for more info.
        """
        raise NotImplementedError("You must implement __call__")


class Middleware(Application): # pylint: disable-msg=W0223
    """Base WSGI middleware wrapper. These classes require an
    application to be initialized that will be called next."""

    def __init__(self, application): # pylint: disable-msg=W0231
        self.application = application


class Debug(Middleware):
    """Helper class that can be inserted into any WSGI application chain
    to get information about the request and response."""

    @webob.dec.wsgify
    def __call__(self, req):
        print ("*" * 40) + " REQUEST ENVIRON"
        for key, value in req.environ.items():
            print key, "=", value
        print
        resp = req.get_response(self.application)

        print ("*" * 40) + " RESPONSE HEADERS"
        for (key, value) in resp.headers:
            print key, "=", value
        print

        resp.app_iter = self.print_generator(resp.app_iter)

        return resp

    @staticmethod
    def print_generator(app_iter):
        """
        Iterator that prints the contents of a wrapper string iterator
        when iterated.
        """
        print ("*" * 40) + "BODY"
        for part in app_iter:
            sys.stdout.write(part)
            sys.stdout.flush()
            yield part
        print


class Router(object):
    """
    WSGI middleware that maps incoming requests to targets.
    
    Non-WSGI-app targets have their results converted to a WSGI response
    automatically -- by default, they are serialized according to the Content
    Type from the request.  This behavior can be changed by overriding
    _to_webob_response().
    """
    
    def __init__(self, map, targets):
        """
        Create a router for the given routes.Mapper `map`.

        Each route in `map` must contain either
         - a 'wsgi_app' string or
         - a 'controller' string and an 'action' string.

        'wsgi_app' is a key into the `target` dictionary whose value
        is a WSGI app.  'controller' is a key into `target' whose value is
        a class instance containing the method specified by 'action'.

        Examples:
          map = routes.Mapper()
          targets = { "servers": ServerController(), "blog": BlogWsgiApp() }

          # Explicit mapping of one route to a controller+action
          map.connect(None, "/serverlist", controller="servers", action="list")

          # Controller string is implicitly equal to 2nd param here, and
          # actions are all implicitly defined
          map.resource("server", "servers")

          # Pointing to a WSGI app.  You'll need to specify the {path_info:.*}
          # parameter so the target app can work with just his section of the
          # URL.
          map.connect(None, "/v1.0/{path_info:.*}", wsgi_app="blog")
        """
        self.map = map
        self.targets = targets
        self._router = routes.middleware.RoutesMiddleware(self.__proceed, self.map)

    @webob.dec.wsgify
    def __call__(self, req):
        """
        Route the incoming request to a controller based on self.map.
        If no match, return a 404.
        """
        return self._router

    @webob.dec.wsgify
    def __proceed(self, req):
        # Called by self._router after matching the incoming request to a route
        # and putting the information into req.environ.  Either returns 404, the
        # routed WSGI app, or _to_webob_response(the action result).

        if req.environ['routes.route'] is None:
            return webob.exc.HTTPNotFound()
        match = req.environ['wsgiorg.routing_args'][1]
        if 'wsgi_app' in match:
            app_name = match['wsgi_app']
            app = self.targets[app_name]
            return app
        else:
            kwargs = match.copy()
            controller_name, action = match['controller'], match['action']
            del kwargs['controller']
            del kwargs['action']

            controller = self.targets[controller_name]
            method = getattr(controller, action)
            result = method(**kwargs)
            return self._to_webob_response(req, result)

    def _to_webob_response(self, req, result):
        """
        When routing to a non-WSGI controller+action, the webob.Request and the
        action's result will be passed here to be converted into a
        webob.Response before returning up the WSGI chain.  By default it
        serializes to the requested Content Type.
        """
        return Serializer(req.environ).serialize(result)


class Serializer(object):
    """
    Serializes a dictionary to a Content Type specified by a WSGI environment.
    """

    def __init__(self, environ):
        """Create a serializer based on the given WSGI environment."""
        self.environ = environ

    def serialize(self, data):
        req = webob.Request(self.environ)
        # TODO(gundlach): temp
        if req.accept and 'application/json' in req.accept:
            import json
            return json.dumps(data)
        else:
            return '<xmlified_yeah_baby>' + repr(data) + '</xmlified_yeah_baby>'


class ApiVersionRouter(Router):
    
    def __init__(self):
        map = routes.Mapper()

        map.connect(None, "/v1.0/{path_info:.*}", wsgi_app="rs")
        map.connect(None, "/ec2/{path_info:.*}", wsgi_app="ec2")

        targets = { "rs": RsApiRouter(), "ec2": Ec2ApiRouter() }

        super(ApiVersionRouter, self).__init__(map, targets)

class RsApiRouter(Router):
    def __init__(self):
        map = routes.Mapper()

        map.resource("server", "servers")
        map.resource("image", "images")
        map.resource("flavor", "flavors")
        map.resource("sharedipgroup", "sharedipgroups")

        targets = { 
                'servers': ServerController(),
                'images': ImageController(),
                'flavors': FlavorController(),
                'sharedipgroups': SharedIpGroupController()
                }

        super(RsApiRouter, self).__init__(map, targets)

# TODO(gundlach): temp
class Ec2ApiRouter(object):
    @webob.dec.wsgify
    def __call__(self, req):
        return 'dummy response'
# TODO(gundlach): temp
class ServerController(object):
    def __getattr__(self, key):
        return lambda **args: {key: 'dummy response for %s' % repr(args)}
# TODO(gundlach): temp
ImageController = FlavorController = SharedIpGroupController = ServerController
