import routes
import webob.dec

from nova import wsgi

# TODO(gundlach): temp
class API(wsgi.Router):
    """WSGI entry point for all AWS API requests."""

    def __init__(self):
        mapper = routes.Mapper()

        mapper.connect(None, "{all:.*}", controller="dummy")

        targets = {"dummy": self.dummy }

        super(API, self).__init__(mapper, targets)

    @webob.dec.wsgify
    def dummy(self, req):
        #TODO(gundlach)
        msg = "dummy response -- please hook up __init__() to cloud.py instead"
        return repr({ 'dummy': msg, 
                 'kwargs': repr(req.environ['wsgiorg.routing_args'][1]) })
