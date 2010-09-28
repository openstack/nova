import webob
import webob.dec
import datetime
from nova.wsgi import Router
from nova import auth

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
