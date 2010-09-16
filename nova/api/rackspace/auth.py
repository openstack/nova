import json
from hashlib import sha1
from nova import datastore

class FakeAuth(object):
    def __init__(self, store=datastore.Redis.instance):
        self._store = store()
        self.auth_hash = 'rs_fake_auth'
        self._store.hsetnx(self.auth_hash, 'rs_last_id', 0)

    def authorize_token(self, token):
        user = self._store.hget(self.auth_hash, token) 
        if user:
            return json.loads(user)
        return None

    def authorize_user(self, user, key):
        token = sha1("%s_%s" % (user, key)).hexdigest()
        user = self._store.hget(self.auth_hash, token)
        if not user:
            return None, None
        else:
            return token, json.loads(user)

    def add_user(self, user, key):
        last_id = self._store.hget(self.auth_hash, 'rs_last_id')
        token = sha1("%s_%s" % (user, key)).hexdigest()
        user = {
            'id':last_id,
            'cdn_management_url':'cdn_management_url',
            'storage_url':'storage_url',
            'server_management_url':'server_management_url'
        }
        new_user = self._store.hsetnx(self.auth_hash, token, json.dumps(user))
        if new_user:
            self._store.hincrby(self.auth_hash, 'rs_last_id')
        
