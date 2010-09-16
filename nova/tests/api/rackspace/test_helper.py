import webob
import webob.dec
from nova.wsgi import Router

fake_data_store = {}
auth_hash = 'dummy_hash'

class FakeRedis(object):
    def __init__(self):
        global fake_data_store
        self.store = fake_data_store

    def hsetnx(self, hash_name, key, value):
        if not self.store.has_key(hash_name):
            self.store[hash_name] = {}

        if self.store[hash_name].has_key(key):
            return 0
        self.store[hash_name][key] = value
        return 1

    def hset(self, hash_name, key, value):
        if not self.store.has_key(hash_name):
            self.store[hash_name] = {}

        self.store[hash_name][key] = value
        return 1

    def hget(self, hash_name, key):
        if not self.store[hash_name].has_key(key):
            return None
        return self.store[hash_name][key]

    def hincrby(self, hash_name, key, amount=1):
        self.store[hash_name][key] += amount

class FakeRouter(Router):
    def __init__(self):
        pass

    @webob.dec.wsgify
    def __call__(self, req):
        res = webob.Response()
        res.status = '200'
        res.headers['X-Test-Success'] = 'True'
        return res

def fake_auth_init(self, store=FakeRedis):
    global auth_hash
    self._store = store()
    self.auth_hash = auth_hash

