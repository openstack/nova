import datetime
import json
import time
import webob.exc
import webob.dec
import hashlib
from nova import flags
from nova import auth
from nova import manager
from nova import db
from nova import utils

FLAGS = flags.FLAGS

class Context(object):
    pass

class BasicApiAuthManager(object):
    """ Implements a somewhat rudimentary version of Rackspace Auth"""

    def __init__(self, host=None, db_driver=None):
        if not host:
            host = FLAGS.host
        self.host = host                                                                                                                                     
        if not db_driver:
            db_driver = FLAGS.db_driver                                                                                                                      
        self.db = utils.import_object(db_driver)
        self.auth = auth.manager.AuthManager()
        self.context = Context()
        super(BasicApiAuthManager, self).__init__()

    def authenticate(self, req):
        # Unless the request is explicitly made against /<version>/ don't
        # honor it
        path_info = req.path_info
        if len(path_info) > 1:
            return webob.exc.HTTPUnauthorized()

        try:
            username, key = req.headers['X-Auth-User'], \
                req.headers['X-Auth-Key']
        except KeyError:
            return webob.exc.HTTPUnauthorized()

        username, key = req.headers['X-Auth-User'], req.headers['X-Auth-Key']
        token, user = self._authorize_user(username, key)
        if user and token:
            res = webob.Response()
            res.headers['X-Auth-Token'] = token['token_hash']
            res.headers['X-Server-Management-Url'] = \
                token['server_management_url']
            res.headers['X-Storage-Url'] = token['storage_url']
            res.headers['X-CDN-Management-Url'] = token['cdn_management_url']
            res.content_type = 'text/plain'
            res.status = '204'
            return res
        else:
            return webob.exc.HTTPUnauthorized()

    def authorize_token(self, token_hash):
        """ retrieves user information from the datastore given a token
        
        If the token has expired, returns None
        If the token is not found, returns None
        Otherwise returns the token

        This method will also remove the token if the timestamp is older than
        2 days ago.
        """
        token = self.db.auth_get_token(self.context, token_hash) 
        if token:
            delta = datetime.datetime.now() - token['created_at']
            if delta.days >= 2:
                self.db.auth_destroy_token(self.context, token)
            else:
                user = self.auth.get_user(token['user_id'])
                return { 'id':user['uid'] }
        return None

    def _authorize_user(self, username, key):
        """ Generates a new token and assigns it to a user """
        user = self.auth.get_user_from_access_key(key)
        if user and user['name'] == username:
            token_hash = hashlib.sha1('%s%s%f' % (username, key,
                time.time())).hexdigest()
            token = {}
            token['token_hash'] = token_hash
            token['cdn_management_url'] = ''
            token['server_management_url'] = self._get_server_mgmt_url()
            token['storage_url'] = ''
            token['user_id'] = user['uid']
            self.db.auth_create_token(self.context, token)
            return token, user
        return None, None 

    def _get_server_mgmt_url(self):
        return 'https://%s/v1.0/' % self.host
        
