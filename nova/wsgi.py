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
    """Helper class that can be insertd into any WSGI application chain
    to get information about the request and response."""

    def __call__(self, environ, start_response):
        for key, value in environ.items():
            print key, "=", value
        print
        wrapper = debug_start_response(start_response)
        return debug_print_body(self.application(environ, wrapper))


def debug_start_response(start_response):
    """Wrap the start_response to capture when called."""

    def wrapper(status, headers, exc_info=None):
        """Print out all headers when start_response is called."""
        print status
        for (key, value) in headers:
            print key, "=", value
        print
        start_response(status, headers, exc_info)

    return wrapper


def debug_print_body(body):
    """Print the body of the response as it is sent back."""

    class Wrapper(object):
        """Iterate through all the body parts and print before returning."""

        def __iter__(self):
            for part in body:
                sys.stdout.write(part)
                sys.stdout.flush()
                yield part
            print

    return Wrapper()


class ParsedRoutes(Middleware):
    """Processed parsed routes from routes.middleware.RoutesMiddleware
    and call either the controller if found or the default application
    otherwise."""

    def __call__(self, environ, start_response):
        if environ['routes.route'] is None:
            return self.application(environ, start_response)
        app = environ['wsgiorg.routing_args'][1]['controller']
        return app(environ, start_response)

class MichaelRouter(object):
    """
    My attempt at a routing class.  Just override __init__ to call
    super, then set up routes in self.map.
    """
    
    def __init__(self):
        self.map = routes.Mapper()
        self._router = routes.middleware.RoutesMiddleware(self._proceed, self.map)

    @webob.dec.wsgify
    def __call__(self, req):
        """
        Route the incoming request to a controller based on self.map.
        If no match, return a 404.
        """
        return self._router

    @webob.dec.wsgify
    def _proceed(self, req):
        """
        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ.
        """
        if req.environ['routes.route'] is None:
            return webob.exc.HTTPNotFound()
        match = environ['wsgiorg.routing_args'][1]
        if match.get('_is_wsgi', False):
            wsgiapp = match['controller']
            return req.get_response(wsgiapp)
        else:
            # TODO(gundlach): doubt this is the right way -- and it really
            # feels like this code should exist somewhere already on the
            # internet
            controller, action = match['controller'], match['action']
            delete match['controller']
            delete match['action']
            return _as_response(getattr(controller, action)(**match))

        controller = environ['wsgiorg.routing_args'][1]['controller']
        self._dispatch(controller)

    def _as_response(self, result):
        """
        When routing to a non-wsgi controller+action, its result will
        be passed here before returning up the WSGI chain to be converted
        into a webob.Response





class ApiVersionRouter(MichaelRouter):
    
    def __init__(self):
        super(ApiVersionRouter, self).__init__(self)

        self.map.connect(None, "/v1.0/{path_info:.*}", controller=RsApiRouter())
        self.map.connect(None, "/ec2/{path_info:.*}", controller=Ec2ApiRouter())

class RsApiRouter(MichaelRouter):
    def __init__(self):
        super(RsApiRouter, self).__init__(self)

        self.map.resource("server", "servers", controller=CloudServersServerApi())
        self.map.resource("image", "images", controller=CloudServersImageApi())
        self.map.resource("flavor", "flavors", controller=CloudServersFlavorApi())
        self.map.resource("sharedipgroup", "sharedipgroups",
                          controller=CloudServersSharedIpGroupApi())

class Ec2ApiRouter(object):
    def __getattr__(self, key):
        return lambda *x: {'dummy response': 'i am a dummy response'}
CloudServersServerApi = CloudServersImageApi = CloudServersFlavorApi = \
        CloudServersSharedIpGroupApi = Ec2ApiRouter

class Router(Middleware): # pylint: disable-msg=R0921
    """Wrapper to help setup routes.middleware.RoutesMiddleware."""

    def __init__(self, application):
        self.map = routes.Mapper()
        self._build_map()
        application = ParsedRoutes(application)
        application = routes.middleware.RoutesMiddleware(application, self.map)
        super(Router, self).__init__(application)

    def __call__(self, environ, start_response):
        return self.application(environ, start_response)

    def _build_map(self):
        """Method to create new connections for the routing map."""
        raise NotImplementedError("You must implement _build_map")

    def _connect(self, *args, **kwargs):
        """Wrapper for the map.connect method."""
        self.map.connect(*args, **kwargs)


def route_args(application):
    """Decorator to make grabbing routing args more convenient."""

    def wrapper(self, req):
        """Call application with req and parsed routing args from."""
        return application(self, req, req.environ['wsgiorg.routing_args'][1])

    return wrapper
