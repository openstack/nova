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


class Application(object):
# TODO(gundlach): I think we should toss this class, now that it has no
# purpose.
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


class Middleware(Application):
    """
    Base WSGI middleware wrapper. These classes require an application to be
    initialized that will be called next.  By default the middleware will
    simply call its wrapped app, or you can override __call__ to customize its
    behavior.
    """

    def __init__(self, application): # pylint: disable-msg=W0231
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req): # pylint: disable-msg=W0221
        """Override to implement middleware behavior."""
        return self.application


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
        for (key, value) in resp.headers.iteritems():
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
        print ("*" * 40) + " BODY"
        for part in app_iter:
            sys.stdout.write(part)
            sys.stdout.flush()
            yield part
        print


class Router(object):
    """
    WSGI middleware that maps incoming requests to WSGI apps.
    """

    def __init__(self, mapper):
        """
        Create a router for the given routes.Mapper.

        Each route in `mapper` must specify a 'controller', which is a
        WSGI app to call.  You'll probably want to specify an 'action' as
        well and have your controller be a wsgi.Controller, who will route
        the request to the action method.

        Examples:
          mapper = routes.Mapper()
          sc = ServerController()

          # Explicit mapping of one route to a controller+action
          mapper.connect(None, "/svrlist", controller=sc, action="list")

          # Actions are all implicitly defined
          mapper.resource("server", "servers", controller=sc)

          # Pointing to an arbitrary WSGI app.  You can specify the
          # {path_info:.*} parameter so the target app can be handed just that
          # section of the URL.
          mapper.connect(None, "/v1.0/{path_info:.*}", controller=BlogApp())
        """
        self.map = mapper
        self._router = routes.middleware.RoutesMiddleware(self._dispatch,
                                                          self.map)

    @webob.dec.wsgify
    def __call__(self, req):
        """
        Route the incoming request to a controller based on self.map.
        If no match, return a 404.
        """
        return self._router

    @staticmethod
    @webob.dec.wsgify
    def _dispatch(req):
        """
        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ.  Either returns 404
        or the routed WSGI app's response.
        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return webob.exc.HTTPNotFound()
        app = match['controller']
        return app


class Controller(object):
    """
    WSGI app that reads routing information supplied by RoutesMiddleware
    and calls the requested action method upon itself.  All action methods
    must, in addition to their normal parameters, accept a 'req' argument
    which is the incoming webob.Request.
    """

    @webob.dec.wsgify
    def __call__(self, req):
        """
        Call the method specified in req.environ by RoutesMiddleware.
        """
        arg_dict = req.environ['wsgiorg.routing_args'][1]
        action = arg_dict['action']
        method = getattr(self, action)
        del arg_dict['controller']
        del arg_dict['action']
        arg_dict['req'] = req
        return method(**arg_dict)


class Serializer(object):
    """
    Serializes a dictionary to a Content Type specified by a WSGI environment.
    """

    def __init__(self, environ, metadata=None):
        """
        Create a serializer based on the given WSGI environment.
        'metadata' is an optional dict mapping MIME types to information
        needed to serialize a dictionary to that type.
        """
        self.environ = environ
        self.metadata = metadata or {}

    def to_content_type(self, data):
        """
        Serialize a dictionary into a string.  The format of the string
        will be decided based on the Content Type requested in self.environ:
        by Accept: header, or by URL suffix.
        """
        mimetype = 'application/xml'
        # TODO(gundlach): determine mimetype from request

        if mimetype == 'application/json':
            import json
            return json.dumps(data)
        elif mimetype == 'application/xml':
            metadata = self.metadata.get('application/xml', {})
            # We expect data to contain a single key which is the XML root.
            root_key = data.keys()[0]
            from xml.dom import minidom
            doc = minidom.Document()
            node = self._to_xml_node(doc, metadata, root_key, data[root_key])
            return node.toprettyxml(indent='    ')
        else:
            return repr(data)

    def _to_xml_node(self, doc, metadata, nodename, data):
        """Recursive method to convert data members to XML nodes."""
        result = doc.createElement(nodename)
        if type(data) is list:
            singular = metadata.get('plurals', {}).get(nodename, None)
            if singular is None:
                if nodename.endswith('s'):
                    singular = nodename[:-1]
                else:
                    singular = 'item'
            for item in data:
                node = self._to_xml_node(doc, metadata, singular, item)
                result.appendChild(node)
        elif type(data) is dict:
            attrs = metadata.get('attributes', {}).get(nodename, {})
            for k, v in data.items():
                if k in attrs:
                    result.setAttribute(k, str(v))
                else:
                    node = self._to_xml_node(doc, metadata, k, v)
                    result.appendChild(node)
        else: # atom
            node = doc.createTextNode(str(data))
            result.appendChild(node)
        return result
