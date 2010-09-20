import webob
import webob.dec
from nova.wsgi import Router
from nova import auth

auth_data = {}

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
    @staticmethod
    def auth_get_token(context, token_hash):
        pass

    @staticmethod
    def auth_create_token(context, token, user_id):
        pass

    @staticmethod
    def auth_destroy_token(context, token):
        pass

class FakeAuthManager(object):
    def __init__(self):
        global auth_data
        self.data = auth_data

    def add_user(self, key, user):        
        self.data[key] = user

    def get_user_from_access_key(self, key):
        return self.data.get(key, None)
