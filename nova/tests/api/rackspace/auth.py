import webob
import webob.dec
import unittest
import stubout
import nova.api
import nova.api.rackspace.auth
from nova.tests.api.rackspace import test_helper

class Test(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(nova.api.rackspace.auth.FakeAuth, '__init__',
            test_helper.fake_auth_init)
        ds = test_helper.FakeRedis()
        ds.hset(test_helper.auth_hash, 'rs_last_id', 0)

    def tearDown(self):
        self.stubs.UnsetAll()
        test_helper.fake_data_store = {}

    def test_authorize_user(self):
        auth = nova.api.rackspace.auth.FakeAuth()
        auth.add_user('herp', 'derp')

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'herp'
        req.headers['X-Auth-Key'] = 'derp'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)
        self.assertEqual(result.headers['X-Server-Management-Url'],
            "server_management_url")
        self.assertEqual(result.headers['X-CDN-Management-Url'],
            "cdn_management_url")
        self.assertEqual(result.headers['X-Storage-Url'], "storage_url")

    def test_authorize_token(self):
        auth = nova.api.rackspace.auth.FakeAuth()
        auth.add_user('herp', 'derp')

        req = webob.Request.blank('/v1.0/')
        req.headers['X-Auth-User'] = 'herp'
        req.headers['X-Auth-Key'] = 'derp'
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '204 No Content')
        self.assertEqual(len(result.headers['X-Auth-Token']), 40)
        self.assertEqual(result.headers['X-Server-Management-Url'],
            "server_management_url")
        self.assertEqual(result.headers['X-CDN-Management-Url'],
            "cdn_management_url")
        self.assertEqual(result.headers['X-Storage-Url'], "storage_url")

        token = result.headers['X-Auth-Token']
        self.stubs.Set(nova.api.rackspace, 'APIRouter',
            test_helper.FakeRouter)
        req = webob.Request.blank('/v1.0/fake')
        req.headers['X-Auth-Token'] = token
        result = req.get_response(nova.api.API())
        self.assertEqual(result.status, '200 OK')
        self.assertEqual(result.headers['X-Test-Success'], 'True')

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
