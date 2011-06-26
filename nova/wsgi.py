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

"""Utility methods for working with WSGI servers."""

import os
import sys
from xml.dom import minidom

import eventlet
import eventlet.wsgi
eventlet.patcher.monkey_patch(all=False, socket=True, time=True)
import routes
import routes.middleware
import webob
import webob.dec
import webob.exc
from paste import deploy

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.wsgi')


class WritableLogger(object):
    """A thin wrapper that responds to `write` and logs."""

    def __init__(self, logger, level=logging.DEBUG):
        self.logger = logger
        self.level = level

    def write(self, msg):
        self.logger.log(self.level, msg)


class Server(object):
    """Server class to manage multiple WSGI sockets and applications."""

    def __init__(self, threads=1000):
        self.pool = eventlet.GreenPool(threads)
        self.socket_info = {}

    def start(self, application, port, host='0.0.0.0', key=None, backlog=128):
        """Run a WSGI server with the given application."""
        arg0 = sys.argv[0]
        logging.audit(_('Starting %(arg0)s on %(host)s:%(port)s') % locals())
        socket = eventlet.listen((host, port), backlog=backlog)
        self.pool.spawn_n(self._run, application, socket)
        if key:
            self.socket_info[key] = socket.getsockname()

    def wait(self):
        """Wait until all servers have completed running."""
        try:
            self.pool.waitall()
        except KeyboardInterrupt:
            pass

    def _run(self, application, socket):
        """Start a WSGI server in a new green thread."""
        logger = logging.getLogger('eventlet.wsgi.server')
        eventlet.wsgi.server(socket, application, custom_pool=self.pool,
                             log=WritableLogger(logger))


class Request(webob.Request):
    pass


class Application(object):
    """Base WSGI application wrapper. Subclasses need to implement __call__."""

    @classmethod
    def fake_connection(cls):
        """Return a fake httplib connection object for this Application"""
        class FakeConnection(object):
            """Faked version of httplib.HTTPConnection to talk to app."""
            def __init__(self):
                self.app = cls()

            def request(self, method, url, body=None, headers={}):
                self.req = webob.Request.blank("/" + url.lstrip("/"))
                self.req.remote_addr = '127.0.0.1'
                self.req.method = method
                if headers:
                    self.req.headers = headers
                if body:
                    self.req.body = body

            def getresponse(self):
                res = self.req.get_response(self.app)

                # httplib.Response has a read() method...fake it out
                def fake_reader():
                    return res.body

                setattr(res, 'read', fake_reader)
                return res

        return FakeConnection()

    @classmethod
    def factory(cls, global_config, **local_config):
        """Used for paste app factories in paste.deploy config files.

        Any local configuration (that is, values under the [app:APPNAME]
        section of the paste config) will be passed into the `__init__` method
        as kwargs.

        A hypothetical configuration would look like:

            [app:wadl]
            latest_version = 1.3
            paste.app_factory = nova.api.fancy_api:Wadl.factory

        which would result in a call to the `Wadl` class as

            import nova.api.fancy_api
            fancy_api.Wadl(latest_version='1.3')

        You could of course re-implement the `factory` method in subclasses,
        but using the kwarg passing it shouldn't be necessary.

        """
        return cls(**local_config)

    def __call__(self, environ, start_response):
        r"""Subclasses will probably want to implement __call__ like this:

        @webob.dec.wsgify(RequestClass=Request)
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
        raise NotImplementedError(_('You must implement __call__'))


class Middleware(Application):
    """Base WSGI middleware.

    These classes require an application to be
    initialized that will be called next.  By default the middleware will
    simply call its wrapped app, or you can override __call__ to customize its
    behavior.

    """

    @classmethod
    def factory(cls, global_config, **local_config):
        """Used for paste app factories in paste.deploy config files.

        Any local configuration (that is, values under the [filter:APPNAME]
        section of the paste config) will be passed into the `__init__` method
        as kwargs.

        A hypothetical configuration would look like:

            [filter:analytics]
            redis_host = 127.0.0.1
            paste.filter_factory = nova.api.analytics:Analytics.factory

        which would result in a call to the `Analytics` class as

            import nova.api.analytics
            analytics.Analytics(app_from_paste, redis_host='127.0.0.1')

        You could of course re-implement the `factory` method in subclasses,
        but using the kwarg passing it shouldn't be necessary.

        """
        def _factory(app):
            return cls(app, **local_config)
        return _factory

    def __init__(self, application):
        self.application = application

    def process_request(self, req):
        """Called on each request.

        If this returns None, the next application down the stack will be
        executed. If it returns a response then that response will be returned
        and execution will stop here.

        """
        return None

    def process_response(self, response):
        """Do whatever you'd like to the response."""
        return response

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, req):
        response = self.process_request(req)
        if response:
            return response
        response = req.get_response(self.application)
        return self.process_response(response)


class Debug(Middleware):
    """Helper class for debugging a WSGI application.

    Can be inserted into any WSGI application chain to get information
    about the request and response.

    """

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, req):
        print ('*' * 40) + ' REQUEST ENVIRON'
        for key, value in req.environ.items():
            print key, '=', value
        print
        resp = req.get_response(self.application)

        print ('*' * 40) + ' RESPONSE HEADERS'
        for (key, value) in resp.headers.iteritems():
            print key, '=', value
        print

        resp.app_iter = self.print_generator(resp.app_iter)

        return resp

    @staticmethod
    def print_generator(app_iter):
        """Iterator that prints the contents of a wrapper string."""
        print ('*' * 40) + ' BODY'
        for part in app_iter:
            sys.stdout.write(part)
            sys.stdout.flush()
            yield part
        print


class Router(object):
    """WSGI middleware that maps incoming requests to WSGI apps."""

    def __init__(self, mapper):
        """Create a router for the given routes.Mapper.

        Each route in `mapper` must specify a 'controller', which is a
        WSGI app to call.  You'll probably want to specify an 'action' as
        well and have your controller be an object that can route
        the request to the action-specific method.

        Examples:
          mapper = routes.Mapper()
          sc = ServerController()

          # Explicit mapping of one route to a controller+action
          mapper.connect(None, '/svrlist', controller=sc, action='list')

          # Actions are all implicitly defined
          mapper.resource('server', 'servers', controller=sc)

          # Pointing to an arbitrary WSGI app.  You can specify the
          # {path_info:.*} parameter so the target app can be handed just that
          # section of the URL.
          mapper.connect(None, '/v1.0/{path_info:.*}', controller=BlogApp())

        """
        self.map = mapper
        self._router = routes.middleware.RoutesMiddleware(self._dispatch,
                                                          self.map)

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, req):
        """Route the incoming request to a controller based on self.map.

        If no match, return a 404.

        """
        return self._router

    @staticmethod
    @webob.dec.wsgify(RequestClass=Request)
    def _dispatch(req):
        """Dispatch the request to the appropriate controller.

        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ.  Either returns 404
        or the routed WSGI app's response.

        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return webob.exc.HTTPNotFound()
        app = match['controller']
        return app


def paste_config_file(basename):
    """Find the best location in the system for a paste config file.

    Search Order
    ------------

    The search for a paste config file honors `FLAGS.state_path`, which in a
    version checked out from bzr will be the `nova` directory in the top level
    of the checkout, and in an installation for a package for your distribution
    will likely point to someplace like /etc/nova.

    This method tries to load places likely to be used in development or
    experimentation before falling back to the system-wide configuration
    in `/etc/nova/`.

    * Current working directory
    * the `etc` directory under state_path, because when working on a checkout
      from bzr this will point to the default
    * top level of FLAGS.state_path, for distributions
    * /etc/nova, which may not be diffrerent from state_path on your distro

    """
    configfiles = [basename,
                   os.path.join(FLAGS.state_path, 'etc', 'nova', basename),
                   os.path.join(FLAGS.state_path, 'etc', basename),
                   os.path.join(FLAGS.state_path, basename),
                   '/etc/nova/%s' % basename]
    for configfile in configfiles:
        if os.path.exists(configfile):
            return configfile


def load_paste_configuration(filename, appname):
    """Returns a paste configuration dict, or None."""
    filename = os.path.abspath(filename)
    config = None
    try:
        config = deploy.appconfig('config:%s' % filename, name=appname)
    except LookupError:
        pass
    return config


def load_paste_app(filename, appname):
    """Builds a wsgi app from a paste config, None if app not configured."""
    filename = os.path.abspath(filename)
    app = None
    try:
        app = deploy.loadapp('config:%s' % filename, name=appname)
    except LookupError:
        pass
    return app
