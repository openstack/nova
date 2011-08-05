import base64
import json
import unittest
from xml.dom import minidom

import stubout
import webob

from nova import context
from nova import db
from nova import utils
from nova.api.openstack import create_instance_helper
from nova.compute import instance_types
from nova.compute import power_state
import nova.db.api
from nova import test
from nova.tests.api.openstack import common
from nova.tests.api.openstack import fakes


def return_server_by_id(context, id):
    return _get_instance()


def instance_update(context, instance_id, kwargs):
    return _get_instance()


def return_server_with_power_state(power_state):
    def _return_server(context, id):
        instance = _get_instance()
        instance['state'] = power_state
        return instance
    return _return_server


def return_server_with_uuid_and_power_state(power_state):
    def _return_server(context, id):
        return return_server_with_power_state(power_state)
    return _return_server


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


def _get_instance():
    instance = {
        "id": 1,
        "created_at": "2010-10-10 12:00:00",
        "updated_at": "2010-11-11 11:00:00",
        "admin_pass": "",
        "user_id": "",
        "project_id": "",
        "image_ref": "5",
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": "",
        "key_data": "",
        "state": 0,
        "state_description": "",
        "memory_mb": 0,
        "vcpus": 0,
        "local_gb": 0,
        "hostname": "",
        "host": "",
        "instance_type": {
           "flavorid": 1,
        },
        "user_data": "",
        "reservation_id": "",
        "mac_address": "",
        "scheduled_at": utils.utcnow(),
        "launched_at": utils.utcnow(),
        "terminated_at": utils.utcnow(),
        "availability_zone": "",
        "display_name": "test_server",
        "display_description": "",
        "locked": False,
        "metadata": [],
        #"address": ,
        #"floating_ips": [{"address":ip} for ip in public_addresses]}
        "uuid": "deadbeef-feed-edee-beef-d0ea7beefedd"}

    return instance


class ServerActionsTest(test.TestCase):

    def setUp(self):
        self.maxDiff = None
        super(ServerActionsTest, self).setUp()
        self.flags(verbose=True)
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db.api, 'instance_get', return_server_by_id)
        self.stubs.Set(nova.db.api, 'instance_update', instance_update)

        self.webreq = common.webob_factory('/v1.0/servers')

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_server_change_password(self):
        body = {'changePassword': {'adminPass': '1234pass'}}
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 501)

    def test_server_change_password_xml(self):
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/xml'
        req.body = '<changePassword adminPass="1234pass">'
#        res = req.get_response(fakes.wsgi_app())
#        self.assertEqual(res.status_int, 501)

    def test_server_reboot(self):
        body = dict(server=dict(
            name='server_test', imageId=2, flavorId=2, metadata={},
            personality={}))
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

    def test_server_rebuild_accepted(self):
        body = {
            "rebuild": {
                "imageId": 2,
            },
        }

        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(res.body, "")

    def test_server_rebuild_rejected_when_building(self):
        body = {
            "rebuild": {
                "imageId": 2,
            },
        }

        state = power_state.BUILDING
        new_return_server = return_server_with_power_state(state)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_with_uuid_and_power_state(state))

        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 409)

    def test_server_rebuild_bad_entity(self):
        body = {
            "rebuild": {
            },
        }

        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_resize_server(self):
        req = self.webreq('/1/action', 'POST', dict(resize=dict(flavorId=3)))

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(self.resize_called, True)

    def test_resize_bad_flavor_fails(self):
        req = self.webreq('/1/action', 'POST', dict(resize=dict(derp=3)))

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        self.assertEqual(self.resize_called, False)

    def test_resize_raises_fails(self):
        req = self.webreq('/1/action', 'POST', dict(resize=dict(flavorId=3)))

        def resize_mock(*args):
            raise Exception('hurr durr')

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 500)

    def test_resized_server_has_correct_status(self):
        req = self.webreq('/1', 'GET')

        def fake_migration_get(*args):
            return {}

        self.stubs.Set(nova.db, 'migration_get_by_instance_and_status',
                fake_migration_get)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        body = json.loads(res.body)
        self.assertEqual(body['server']['status'], 'RESIZE-CONFIRM')

    def test_confirm_resize_server(self):
        req = self.webreq('/1/action', 'POST', dict(confirmResize=None))

        self.resize_called = False

        def confirm_resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'confirm_resize',
                confirm_resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 204)
        self.assertEqual(self.resize_called, True)

    def test_confirm_resize_server_fails(self):
        req = self.webreq('/1/action', 'POST', dict(confirmResize=None))

        def confirm_resize_mock(*args):
            raise Exception('hurr durr')

        self.stubs.Set(nova.compute.api.API, 'confirm_resize',
                confirm_resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_revert_resize_server(self):
        req = self.webreq('/1/action', 'POST', dict(revertResize=None))

        self.resize_called = False

        def revert_resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'revert_resize',
                revert_resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(self.resize_called, True)

    def test_revert_resize_server_fails(self):
        req = self.webreq('/1/action', 'POST', dict(revertResize=None))

        def revert_resize_mock(*args):
            raise Exception('hurr durr')

        self.stubs.Set(nova.compute.api.API, 'revert_resize',
                revert_resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_migrate_server(self):
        """This is basically the same as resize, only we provide the `migrate`
        attribute in the body's dict.
        """
        req = self.webreq('/1/migrate', 'POST')

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(self.resize_called, True)

    def test_create_backup(self):
        """The happy path for creating backups"""
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        self.assertTrue(response.headers['Location'])

    def test_create_backup_admin_api_off(self):
        """The happy path for creating backups"""
        self.flags(allow_admin_api=False)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(501, response.status_int)

    def test_create_backup_with_metadata(self):
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': {'123': 'asdf'},
            },
        }

        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        self.assertTrue(response.headers['Location'])

    def test_create_backup_no_name(self):
        """Name is required for backups"""
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        req = webob.Request.blank('/v1.0/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_backup_no_rotation(self):
        """Rotation is required for backup requests"""
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
            },
        }

        req = webob.Request.blank('/v1.0/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_backup_no_backup_type(self):
        """Backup Type (daily or weekly) is required for backup requests"""
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'rotation': 1,
            },
        }
        req = webob.Request.blank('/v1.0/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_backup_bad_entity(self):
        self.flags(allow_admin_api=True)

        body = {'createBackup': 'go'}
        req = webob.Request.blank('/v1.0/images')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"

        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)


class ServerActionsTestV11(test.TestCase):

    def setUp(self):
        self.maxDiff = None
        super(ServerActionsTestV11, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db.api, 'instance_get', return_server_by_id)
        self.stubs.Set(nova.db.api, 'instance_update', instance_update)

        fakes.stub_out_glance(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        service_class = 'nova.image.glance.GlanceImageService'
        self.service = utils.import_object(service_class)
        self.context = context.RequestContext(1, None)
        self.service.delete_all()
        self.sent_to_glance = {}
        fakes.stub_out_glance_add_image(self.stubs, self.sent_to_glance)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_server_change_password(self):
        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)
        body = {'changePassword': {'adminPass': '1234pass'}}
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(mock_method.instance_id, '1')
        self.assertEqual(mock_method.password, '1234pass')

    def test_server_change_password_not_a_string(self):
        body = {'changePassword': {'adminPass': 1234}}
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password_bad_request(self):
        body = {'changePassword': {'pass': '12345'}}
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password_none(self):
        body = {'changePassword': {'adminPass': None}}
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_rebuild_accepted_minimum(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_rebuild_rejected_when_building(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        state = power_state.BUILDING
        new_return_server = return_server_with_power_state(state)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_with_uuid_and_power_state(state))

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 409)

    def test_server_rebuild_accepted_with_metadata(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "metadata": {
                    "new": "metadata",
                },
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_rebuild_accepted_with_bad_metadata(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "metadata": "stack",
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_rebuild_bad_entity(self):
        body = {
            "rebuild": {
                "imageId": 2,
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_rebuild_bad_personality(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "personality": [{
                    "path": "/path/to/file",
                    "contents": "INVALID b64",
                }]
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_rebuild_personality(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "personality": [{
                    "path": "/path/to/file",
                    "contents": base64.b64encode("Test String"),
                }]
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_resize_server(self):

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.content_type = 'application/json'
        req.method = 'POST'
        body_dict = dict(resize=dict(flavorRef="http://localhost/3"))
        req.body = json.dumps(body_dict)

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(self.resize_called, True)

    def test_create_image(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        location = response.headers['Location']
        self.assertEqual('http://localhost/v1.1/images/123', location)

    def test_create_image_with_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {'key': 'asdf'},
            },
        }
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        location = response.headers['Location']
        self.assertEqual('http://localhost/v1.1/images/123', location)

    def test_create_image_no_name(self):
        body = {
            'createImage': {},
        }
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_image_bad_metadata(self):
        body = {
            'createImage': {
                'name': 'geoff',
                'metadata': 'henry',
            },
        }
        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_backup(self):
        """The happy path for creating backups"""
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
            },
        }

        req = webob.Request.blank('/v1.1/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        self.assertTrue(response.headers['Location'])


class TestServerActionXMLDeserializer(test.TestCase):

    def setUp(self):
        self.deserializer = create_instance_helper.ServerXMLDeserializer()

    def tearDown(self):
        pass

    def test_create_image(self):
        serial_request = """
<createImage xmlns="http://docs.openstack.org/compute/api/v1.1"
             name="new-server-test"/>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "createImage": {
                "name": "new-server-test",
                "metadata": {},
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_image_with_metadata(self):
        serial_request = """
<createImage xmlns="http://docs.openstack.org/compute/api/v1.1"
             name="new-server-test">
    <metadata>
        <meta key="key1">value1</meta>
    </metadata>
</createImage>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "createImage": {
                "name": "new-server-test",
                "metadata": {"key1": "value1"},
            },
        }
        self.assertEquals(request['body'], expected)
