import webob.dec

class APIStub(object):
    """Class to verify request and mark it was called."""
    @webob.dec.wsgify
    def __call__(self, req):
        return req.path_info
