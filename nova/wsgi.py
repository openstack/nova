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

    def start(self, application, port, host='0.0.0.0', backlog=128):
        """Run a WSGI server with the given application."""
        arg0 = sys.argv[0]
        logging.audit(_('Starting %(arg0)s on %(host)s:%(port)s') % locals())
        socket = eventlet.listen((host, port), backlog=backlog)
        self.pool.spawn_n(self._run, application, socket)

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

    def best_match_content_type(self):
        """Determine the most acceptable content-type.

        Based on the query extension then the Accept header.

        """
        parts = self.path.rsplit('.', 1)

        if len(parts) > 1:
            format = parts[1]
            if format in ['json', 'xml']:
                return 'application/{0}'.format(parts[1])

        ctypes = ['application/json', 'application/xml']
        bm = self.accept.best_match(ctypes)

        return bm or 'application/json'

    def get_content_type(self):
        try:
            ct = self.headers['Content-Type']
            assert ct in ('application/xml', 'application/json')
            return ct
        except Exception:
            raise webob.exc.HTTPBadRequest('Invalid content type')


class Application(object):
    """Base WSGI application wrapper. Subclasses need to implement __call__."""

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
        well and have your controller be a wsgi.Controller, who will route
        the request to the action method.

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


class Controller(object):
    """WSGI app that dispatched to methods.

    WSGI app that reads routing information supplied by RoutesMiddleware
    and calls the requested action method upon itself.  All action methods
    must, in addition to their normal parameters, accept a 'req' argument
    which is the incoming wsgi.Request.  They raise a webob.exc exception,
    or return a dict which will be serialized by requested content type.

    """

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, req):
        """Call the method specified in req.environ by RoutesMiddleware."""
        arg_dict = req.environ['wsgiorg.routing_args'][1]
        action = arg_dict['action']
        method = getattr(self, action)
        LOG.debug("%s %s" % (req.method, req.url))
        del arg_dict['controller']
        del arg_dict['action']
        if 'format' in arg_dict:
            del arg_dict['format']
        arg_dict['req'] = req
        result = method(**arg_dict)

        if type(result) is dict:
            content_type = req.best_match_content_type()
            default_xmlns = self.get_default_xmlns(req)
            body = self._serialize(result, content_type, default_xmlns)

            response = webob.Response()
            response.headers['Content-Type'] = content_type
            response.body = body
            msg_dict = dict(url=req.url, status=response.status_int)
            msg = _("%(url)s returned with HTTP %(status)d") % msg_dict
            LOG.debug(msg)
            return response
        else:
            return result

    def _serialize(self, data, content_type, default_xmlns):
        """Serialize the given dict to the provided content_type.

        Uses self._serialization_metadata if it exists, which is a dict mapping
        MIME types to information needed to serialize to that type.

        """
        _metadata = getattr(type(self), '_serialization_metadata', {})

        serializer = Serializer(_metadata, default_xmlns)
        try:
            return serializer.serialize(data, content_type)
        except exception.InvalidContentType:
            raise webob.exc.HTTPNotAcceptable()

    def _deserialize(self, data, content_type):
        """Deserialize the request body to the specefied content type.

        Uses self._serialization_metadata if it exists, which is a dict mapping
        MIME types to information needed to serialize to that type.

        """
        _metadata = getattr(type(self), '_serialization_metadata', {})
        serializer = Serializer(_metadata)
        return serializer.deserialize(data, content_type)

    def get_default_xmlns(self, req):
        """Provide the XML namespace to use if none is otherwise specified."""
        return None


class Serializer(object):
    """Serializes and deserializes dictionaries to certain MIME types."""

    def __init__(self, metadata=None, default_xmlns=None):
        """Create a serializer based on the given WSGI environment.

        'metadata' is an optional dict mapping MIME types to information
        needed to serialize a dictionary to that type.

        """
        self.metadata = metadata or {}
        self.default_xmlns = default_xmlns

    def _get_serialize_handler(self, content_type):
        handlers = {
            'application/json': self._to_json,
            'application/xml': self._to_xml,
        }

        try:
            return handlers[content_type]
        except Exception:
            raise exception.InvalidContentType()

    def serialize(self, data, content_type):
        """Serialize a dictionary into the specified content type."""
        return self._get_serialize_handler(content_type)(data)

    def deserialize(self, datastring, content_type):
        """Deserialize a string to a dictionary.

        The string must be in the format of a supported MIME type.

        """
        return self.get_deserialize_handler(content_type)(datastring)

    def get_deserialize_handler(self, content_type):
        handlers = {
            'application/json': self._from_json,
            'application/xml': self._from_xml,
        }

        try:
            return handlers[content_type]
        except Exception:
            raise exception.InvalidContentType(_('Invalid content type %s'
                                                 % content_type))

    def _from_json(self, datastring):
        return utils.loads(datastring)

    def _from_xml(self, datastring):
        xmldata = self.metadata.get('application/xml', {})
        plurals = set(xmldata.get('plurals', {}))
        node = minidom.parseString(datastring).childNodes[0]
        return {node.nodeName: self._from_xml_node(node, plurals)}

    def _from_xml_node(self, node, listnames):
        """Convert a minidom node to a simple Python type.

        listnames is a collection of names of XML nodes whose subnodes should
        be considered list items.

        """
        if len(node.childNodes) == 1 and node.childNodes[0].nodeType == 3:
            return node.childNodes[0].nodeValue
        elif node.nodeName in listnames:
            return [self._from_xml_node(n, listnames) for n in node.childNodes]
        else:
            result = dict()
            for attr in node.attributes.keys():
                result[attr] = node.attributes[attr].nodeValue
            for child in node.childNodes:
                if child.nodeType != node.TEXT_NODE:
                    result[child.nodeName] = self._from_xml_node(child,
                                                                 listnames)
            return result

    def _to_json(self, data):
        return utils.dumps(data)

    def _to_xml(self, data):
        metadata = self.metadata.get('application/xml', {})
        # We expect data to contain a single key which is the XML root.
        root_key = data.keys()[0]
        doc = minidom.Document()
        node = self._to_xml_node(doc, metadata, root_key, data[root_key])

        xmlns = node.getAttribute('xmlns')
        if not xmlns and self.default_xmlns:
            node.setAttribute('xmlns', self.default_xmlns)

        return node.toprettyxml(indent='    ')

    def _to_xml_node(self, doc, metadata, nodename, data):
        """Recursive method to convert data members to XML nodes."""
        result = doc.createElement(nodename)

        # Set the xml namespace if one is specified
        # TODO(justinsb): We could also use prefixes on the keys
        xmlns = metadata.get('xmlns', None)
        if xmlns:
            result.setAttribute('xmlns', xmlns)

        if type(data) is list:
            collections = metadata.get('list_collections', {})
            if nodename in collections:
                metadata = collections[nodename]
                for item in data:
                    node = doc.createElement(metadata['item_name'])
                    node.setAttribute(metadata['item_key'], str(item))
                    result.appendChild(node)
                return result
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
            collections = metadata.get('dict_collections', {})
            if nodename in collections:
                metadata = collections[nodename]
                for k, v in data.items():
                    node = doc.createElement(metadata['item_name'])
                    node.setAttribute(metadata['item_key'], str(k))
                    text = doc.createTextNode(str(v))
                    node.appendChild(text)
                    result.appendChild(node)
                return result
            attrs = metadata.get('attributes', {}).get(nodename, {})
            for k, v in data.items():
                if k in attrs:
                    result.setAttribute(k, str(v))
                else:
                    node = self._to_xml_node(doc, metadata, k, v)
                    result.appendChild(node)
        else:
            # Type is atom
            node = doc.createTextNode(str(data))
            result.appendChild(node)
        return result


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
