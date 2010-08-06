import eventletserver
import carrot.connection
import carrot.messaging
import itertools
import routes


# See http://pythonpaste.org/webob/ for usage
from webob.dec import wsgify
from webob import exc, Request, Response
 
class WSGILayer(object):
    def __init__(self, application=None):
        self.application = application
 
    def __call__(self, environ, start_response):
        # Subclasses will probably want to implement __call__ like this:
        #
        # @wsgify
        # def __call__(self, req):
        #   # Any of the following objects work as responses:
        #
        #   # Option 1: simple string
        #   resp = 'message\n'
        #
        #   # Option 2: a nicely formatted HTTP exception page
        #   resp = exc.HTTPForbidden(detail='Nice try')
        #
        #   # Option 3: a webob Response object (in case you need to play with
        #   # headers, or you want to be treated like an iterable, or or or)
        #   resp = Response(); resp.app_iter = open('somefile')
        #
        #   # Option 4: any wsgi app to be run next
        #   resp = self.application
        #
        #   # Option 5: you can get a Response object for a wsgi app, too, to
        #   # play with headers etc
        #   resp = req.get_response(self.application)
        #
        #
        #   # You can then just return your response...
        #   return resp         # option 1
        #   # ... or set req.response and return None.
        #   req.response = resp # option 2
        #
        # See the end of http://pythonpaste.org/webob/modules/dec.html 
        # for more info.
        raise NotImplementedError("You must implement __call__")
        
 
class WsgiStack(WSGILayer):
    def __init__(self, wsgi_layers):
        bottom_up = list(reversed(wsgi_layers))
        app, remaining = bottom_up[0], bottom_up[1:]
        for layer in remaining:
            layer.application = app
            app = layer
        super(WsgiStack, self).__init__(app)

    @wsgify
    def __call__(self, req):
        return self.application

class Debug(WSGILayer):
    @wsgify
    def __call__(self, req):
        for k, v in req.environ.items():
            print k, "=", v
        return self.application
 
class Auth(WSGILayer):
    @wsgify
    def __call__(self, req):
        if not 'openstack.auth.token' in req.environ:
            # Check auth params here
            if True:
                req.environ['openstack.auth.token'] = '12345'
            else:
                return exc.HTTPForbidden(detail="Go away")
     
        response = req.get_response(self.application)
        response.headers['X-Openstack-Auth'] = 'Success'
        return response
 
class Router(WSGILayer):
    def __init__(self, application=None):
        super(Router, self).__init__(application)
        self.map = routes.Mapper()
        self._connect()
 
    @wsgify
    def __call__(self, req):
        match = self.map.match(req.path_info)
        if match is None:
            return self.application
        req.environ['openstack.match'] = match
        return match['controller']
 
    def _connect(self):
        raise NotImplementedError("You must implement _connect")
 
class FileRouter(Router):
    def _connect(self):
        self.map.connect(None, '/files/{file}', controller=File())
        self.map.connect(None, '/rfiles/{file}', controller=Reverse(File()))
 
class Message(WSGILayer):
    @wsgify
    def __call__(self, req):
        return 'message\n'
 
class Reverse(WSGILayer):
    @wsgify
    def __call__(self, req):
        inner_resp = req.get_response(self.application)
        resp = Response()
        resp.app_iter = itertools.imap(lambda x: x[::-1], inner_resp.app_iter)
        return resp
 
class File(WSGILayer):
    @wsgify
    def __call__(self, req):
        try:
            myfile = open(req.environ['openstack.match']['file'])
        except IOError, e:
            raise exc.HTTPNotFound()
        req.response = Response()
        req.response.app_iter = myfile
 
wsgi_layers = [
        Auth(),
        Debug(),
        FileRouter(),
        Message(),
        ]
eventletserver.serve(app=WsgiStack(wsgi_layers), port=12345)
