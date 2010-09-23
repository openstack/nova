import webob
import webob.dec
import unittest
import stubout
import nova.api
import nova.api.rackspace.auth
from nova import auth
from nova.tests.api.rackspace import test_helper
import datetime

class Test(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(nova.api.rackspace.auth.BasicApiAuthManager,
            '__init__', test_helper.fake_auth_init)
        test_helper.FakeAuthManager.auth_data = {}
        test_helper.FakeAuthDatabase.data = {}
        self.stubs.Set(nova.api.rackspace, 'RateLimitingMiddleware',
            test_helper.FakeRateLimiter)

    def tearDown(self):
        self.stubs.UnsetAll()
        test_helper.fake_data_store = {}

    def test_authorize_user(self):
        f = test_helper.FakeAuthManager()
        f.add_user('derp', { 'uid': 1, 'name':'herp' } )

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'herp'
        req.headers['X-Auth-Key'] = 'derp'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)
        self.assertEqual(result.headers['X-CDN-Management-Url'],
            "")
        self.assertEqual(result.headers['X-Storage-Url'], "")

    def test_authorize_token(self):
        f = test_helper.FakeAuthManager()
        f.add_user('derp', { 'uid': 1, 'name':'herp' } )
            
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'herp'
        req.headers['X-Auth-Key'] = 'derp'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)
        self.assertEqual(result.headers['X-Server-Management-Url'],
            "https://foo/v1.0/")
        self.assertEqual(result.headers['X-CDN-Management-Url'],
            "")
        self.assertEqual(result.headers['X-Storage-Url'], "")

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.rackspace, 'APIRouter',
            test_helper.FakeRouter)
        req = webob.Request.blank('/v1.0/fake')
        req.headers['X-Auth-Token'] = token
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '200 OK')
        self.assertEqual(result.headers['X-Test-Success'], 'True')
    
    def test_token_expiry(self):
        self.destroy_called = False
        token_hash = 'bacon'

        def destroy_token_mock(meh, context, token):
            self.destroy_called = True
        
        def bad_token(meh, context, token_hash):
            return { 'token_hash':token_hash,  
                     'created_at':datetime.datetime(1990, 1, 1) }

        self.stubs.Set(test_helper.FakeAuthDatabase, 'auth_destroy_token',
            destroy_token_mock)

        self.stubs.Set(test_helper.FakeAuthDatabase, 'auth_get_token',
            bad_token)

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = 'bacon'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '401 Unauthorized')
        self.assertEqual(self.destroy_called, True)

    def test_bad_user(self):
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'herp'
        req.headers['X-Auth-Key'] = 'derp'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '401 Unauthorized')

    def test_no_user(self):
        req = webob.Request.blank('/v1.0/')
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '401 Unauthorized')

    def test_bad_token(self):
        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-Token'] = 'baconbaconbacon'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '401 Unauthorized')

if __name__ == '__main__':
    unittest.main()
