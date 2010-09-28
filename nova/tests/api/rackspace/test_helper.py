import json
import webob
import webob.dec
import datetime
import nova.api.rackspace.auth
import nova.api.rackspace._id_translator
from nova.wsgi import Router
from nova import auth
from nova import utils
from nova import flags

FLAGS = flags.FLAGS

class Context(object): 
    pass

class FakeRouter(Router):
    def __init__(self):
        pass

    @webob.dec.wsgify
    def __call__(self, req):
        res = webob.Response()
        res.status = '200'
        res.headers['X-Test-Success'] = 'True'
        return res

def fake_auth_init(self):
    self.db = FakeAuthDatabase()
    self.context = Context()
    self.auth = FakeAuthManager()
    self.host = 'foo'

@webob.dec.wsgify
def fake_wsgi(self, req):
    req.environ['nova.context'] = dict(user=dict(id=1))
    if req.body:
        req.environ['inst_dict'] = json.loads(req.body)
    return self.application

def stub_out_image_translator(stubs):
    class FakeTranslator(object):
        def __init__(self, id_type, service_name):
            pass
        
        def to_rs_id(self, id):
            return id

        def from_rs_id(self, id):
            return id

    stubs.Set(nova.api.rackspace._id_translator,
        'RackspaceAPIIdTranslator', FakeTranslator)

def stub_out_auth(stubs):
    def fake_auth_init(self, app):
        self.application = app
    
    stubs.Set(nova.api.rackspace.AuthMiddleware, 
        '__init__', fake_auth_init) 
    stubs.Set(nova.api.rackspace.AuthMiddleware, 
        '__call__', fake_wsgi) 

def stub_out_rate_limiting(stubs):
    def fake_rate_init(self, app):
        super(nova.api.rackspace.RateLimitingMiddleware, self).__init__(app)
        self.application = app

    stubs.Set(nova.api.rackspace.RateLimitingMiddleware,
        '__init__', fake_rate_init)

    stubs.Set(nova.api.rackspace.RateLimitingMiddleware,
        '__call__', fake_wsgi)

def stub_for_testing(stubs):
    def get_my_ip():
        return '127.0.0.1' 
    stubs.Set(nova.utils, 'get_my_ip', get_my_ip)
    FLAGS.FAKE_subdomain = 'rs'

class FakeAuthDatabase(object):
    data = {}

    @staticmethod
    def auth_get_token(context, token_hash):
        return FakeAuthDatabase.data.get(token_hash, None)

    @staticmethod
    def auth_create_token(context, token):
        token['created_at'] = datetime.datetime.now()
        FakeAuthDatabase.data[token['token_hash']] = token

    @staticmethod
    def auth_destroy_token(context, token):
        if FakeAuthDatabase.data.has_key(token['token_hash']):
            del FakeAuthDatabase.data['token_hash']

class FakeAuthManager(object):
    auth_data = {}

    def add_user(self, key, user):        
        FakeAuthManager.auth_data[key] = user

    def get_user(self, uid):
        for k, v in FakeAuthManager.auth_data.iteritems():
            if v['uid'] == uid:
                return v
        return None

    def get_user_from_access_key(self, key):
        return FakeAuthManager.auth_data.get(key, None)

class FakeRateLimiter(object):
    def __init__(self, application):
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req):
        return self.application
