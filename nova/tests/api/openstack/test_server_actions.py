import base64
import datetime
import json

import stubout
import webob

from nova import context
from nova import utils
from nova import exception
from nova import flags
from nova.api.openstack import create_instance_helper
from nova.compute import vm_states
from nova.compute import instance_types
import nova.db.api
from nova import test
from nova.tests.api.openstack import common
from nova.tests.api.openstack import fakes


FLAGS = flags.FLAGS


def return_server_by_id(context, id):
    return stub_instance(id)


def instance_update(context, instance_id, kwargs):
    return stub_instance(instance_id)


def return_server_with_attributes(**kwargs):
    def _return_server(context, id):
        return stub_instance(id, **kwargs)
    return _return_server


def return_server_with_state(vm_state, task_state=None):
    return return_server_with_attributes(vm_state=vm_state,
                                         task_state=task_state)


def return_server_with_uuid_and_state(vm_state, task_state=None):
    def _return_server(context, id):
        return return_server_with_state(vm_state, task_state)
    return _return_server


def stub_instance(id, metadata=None, image_ref="10", flavor_id="1",
                  name=None, vm_state=None, task_state=None):
    if metadata is not None:
        metadata_items = [{'key':k, 'value':v} for k, v in metadata.items()]
    else:
        metadata_items = [{'key':'seq', 'value':id}]

    inst_type = instance_types.get_instance_type_by_flavor_id(int(flavor_id))

    instance = {
        "id": int(id),
        "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
        "admin_pass": "",
        "user_id": "fake",
        "project_id": "fake",
        "image_ref": image_ref,
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": "",
        "key_data": "",
        "vm_state": vm_state or vm_states.ACTIVE,
        "task_state": task_state,
        "memory_mb": 0,
        "vcpus": 0,
        "local_gb": 0,
        "hostname": "",
        "host": "",
        "instance_type": dict(inst_type),
        "user_data": "",
        "reservation_id": "",
        "mac_address": "",
        "scheduled_at": utils.utcnow(),
        "launched_at": utils.utcnow(),
        "terminated_at": utils.utcnow(),
        "availability_zone": "",
        "display_name": name or "server%s" % id,
        "display_description": "",
        "locked": False,
        "metadata": metadata_items,
        "access_ip_v4": "",
        "access_ip_v6": "",
        "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "virtual_interfaces": [],
    }

    instance["fixed_ips"] = {
        "address": '192.168.0.1',
        "floating_ips": [],
    }

    return instance


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


class ServerActionsTest(test.TestCase):

    def setUp(self):
        self.maxDiff = None
        super(ServerActionsTest, self).setUp()
        self.flags(verbose=True)
        self.stubs = stubout.StubOutForTesting()
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

        state = vm_states.BUILDING
        new_return_server = return_server_with_state(state)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_with_uuid_and_state(state))

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

    def test_confirm_resize_migration_not_found(self):
        req = self.webreq('/1/action', 'POST', dict(confirmResize=None))

        def confirm_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stubs.Set(nova.compute.api.API,
                       'confirm_resize',
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

    def test_revert_resize_migration_not_found(self):
        req = self.webreq('/1/action', 'POST', dict(revertResize=None))

        def revert_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stubs.Set(nova.compute.api.API,
                       'revert_resize',
                       revert_resize_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

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
        self.assertEqual(400, response.status_int)

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

    def test_create_backup_with_too_much_metadata(self):
        self.flags(allow_admin_api=True)

        body = {
            'createBackup': {
                'name': 'Backup 1',
                'backup_type': 'daily',
                'rotation': 1,
                'metadata': {'123': 'asdf'},
            },
        }
        for num in range(FLAGS.quota_metadata_items + 1):
            body['createBackup']['metadata']['foo%i' % num] = "bar"
        req = webob.Request.blank('/v1.0/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(413, response.status_int)

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
        self.flags(allow_instance_snapshots=True)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_server_bad_body(self):
        body = {}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_unknown_action(self):
        body = {'sockTheFox': {'fakekey': '1234'}}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password(self):
        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)
        body = {'changePassword': {'adminPass': '1234pass'}}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(mock_method.instance_id, '1')
        self.assertEqual(mock_method.password, '1234pass')

    def test_server_change_password_xml(self):
        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = "application/xml"
        req.body = """<?xml version="1.0" encoding="UTF-8"?>
                    <changePassword
                        xmlns="http://docs.openstack.org/compute/api/v1.1"
                        adminPass="1234pass"/>"""
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(mock_method.instance_id, '1')
        self.assertEqual(mock_method.password, '1234pass')

    def test_server_change_password_not_a_string(self):
        body = {'changePassword': {'adminPass': 1234}}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password_bad_request(self):
        body = {'changePassword': {'pass': '12345'}}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_change_password_none(self):
        body = {'changePassword': {'adminPass': None}}
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_reboot_hard(self):
        body = dict(reboot=dict(type="HARD"))
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_reboot_soft(self):
        body = dict(reboot=dict(type="SOFT"))
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_server_reboot_incorrect_type(self):
        body = dict(reboot=dict(type="NOT_A_TYPE"))
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_reboot_missing_type(self):
        body = dict(reboot=dict())
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_server_rebuild_accepted_minimum(self):
        new_return_server = return_server_with_attributes(image_ref='2')
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        body = json.loads(res.body)
        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(len(body['server']['adminPass']), 16)

    def test_server_rebuild_rejected_when_building(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        state = vm_states.BUILDING
        new_return_server = return_server_with_state(state)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_with_uuid_and_state(state))

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 409)

    def test_server_rebuild_accepted_with_metadata(self):
        metadata = {'new': 'metadata'}

        new_return_server = return_server_with_attributes(metadata=metadata)
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "metadata": metadata,
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        body = json.loads(res.body)
        self.assertEqual(body['server']['metadata'], metadata)

    def test_server_rebuild_accepted_with_bad_metadata(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "metadata": "stack",
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
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

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
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

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
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

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        body = json.loads(res.body)
        self.assertTrue('personality' not in body['server'])

    def test_server_rebuild_admin_pass(self):
        new_return_server = return_server_with_attributes(image_ref='2')
        self.stubs.Set(nova.db.api, 'instance_get', new_return_server)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "adminPass": "asdf",
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        body = json.loads(res.body)
        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(body['server']['adminPass'], 'asdf')

    def test_server_rebuild_server_not_found(self):
        def server_not_found(self, instance_id):
            raise exception.InstanceNotFound(instance_id=instance_id)
        self.stubs.Set(nova.db.api, 'instance_get', server_not_found)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.content_type = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_resize_server(self):

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
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

    def test_resize_server_no_flavor(self):
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.content_type = 'application/json'
        req.method = 'POST'
        body_dict = dict(resize=dict())
        req.body = json.dumps(body_dict)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_resize_server_no_flavor_ref(self):
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.content_type = 'application/json'
        req.method = 'POST'
        body_dict = dict(resize=dict(flavorRef=None))
        req.body = json.dumps(body_dict)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_confirm_resize_server(self):
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.content_type = 'application/json'
        req.method = 'POST'
        body_dict = dict(confirmResize=None)
        req.body = json.dumps(body_dict)

        self.confirm_resize_called = False

        def cr_mock(*args):
            self.confirm_resize_called = True

        self.stubs.Set(nova.compute.api.API, 'confirm_resize', cr_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 204)
        self.assertEqual(self.confirm_resize_called, True)

    def test_revert_resize_server(self):
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.content_type = 'application/json'
        req.method = 'POST'
        body_dict = dict(revertResize=None)
        req.body = json.dumps(body_dict)

        self.revert_resize_called = False

        def revert_mock(*args):
            self.revert_resize_called = True

        self.stubs.Set(nova.compute.api.API, 'revert_resize', revert_mock)

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)
        self.assertEqual(self.revert_resize_called, True)

    def test_create_image(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        location = response.headers['Location']
        self.assertEqual('http://localhost/v1.1/fake/images/123', location)

    def test_create_image_snapshots_disabled(self):
        """Don't permit a snapshot if the allow_instance_snapshots flag is
        False
        """
        self.flags(allow_instance_snapshots=False)
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(400, response.status_int)

    def test_create_image_with_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {'key': 'asdf'},
            },
        }
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        location = response.headers['Location']
        self.assertEqual('http://localhost/v1.1/fake/images/123', location)

    def test_create_image_with_too_much_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {},
            },
        }
        for num in range(FLAGS.quota_metadata_items + 1):
            body['createImage']['metadata']['foo%i' % num] = "bar"
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(413, response.status_int)

    def test_create_image_no_name(self):
        body = {
            'createImage': {},
        }
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
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
        req = webob.Request.blank('/v1.1/fake/servers/1/action')
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

        req = webob.Request.blank('/v1.1/fake/servers/1/action')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers["content-type"] = "application/json"
        response = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, response.status_int)
        self.assertTrue(response.headers['Location'])


class TestServerActionXMLDeserializerV11(test.TestCase):

    def setUp(self):
        self.deserializer = create_instance_helper.ServerXMLDeserializerV11()

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

    def test_change_pass(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <changePassword
                    xmlns="http://docs.openstack.org/compute/api/v1.1"
                    adminPass="1234pass"/> """
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "changePassword": {
                "adminPass": "1234pass",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_change_pass_no_pass(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <changePassword
                    xmlns="http://docs.openstack.org/compute/api/v1.1"/> """
        self.assertRaises(AttributeError,
                          self.deserializer.deserialize,
                          serial_request,
                          'action')

    def test_reboot(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <reboot
                    xmlns="http://docs.openstack.org/compute/api/v1.1"
                    type="HARD"/>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "reboot": {
                "type": "HARD",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_reboot_no_type(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <reboot
                    xmlns="http://docs.openstack.org/compute/api/v1.1"/>"""
        self.assertRaises(AttributeError,
                          self.deserializer.deserialize,
                          serial_request,
                          'action')

    def test_resize(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <resize
                    xmlns="http://docs.openstack.org/compute/api/v1.1"
                    flavorRef="http://localhost/flavors/3"/>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "resize": {"flavorRef": "http://localhost/flavors/3"},
        }
        self.assertEquals(request['body'], expected)

    def test_resize_no_flavor_ref(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <resize
                    xmlns="http://docs.openstack.org/compute/api/v1.1"/>"""
        self.assertRaises(AttributeError,
                          self.deserializer.deserialize,
                          serial_request,
                          'action')

    def test_confirm_resize(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <confirmResize
                    xmlns="http://docs.openstack.org/compute/api/v1.1"/>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "confirmResize": None,
        }
        self.assertEquals(request['body'], expected)

    def test_revert_resize(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <revertResize
                   xmlns="http://docs.openstack.org/compute/api/v1.1"/>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "revertResize": None,
        }
        self.assertEquals(request['body'], expected)

    def test_rebuild(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <rebuild
                    xmlns="http://docs.openstack.org/compute/api/v1.1"
                    name="new-server-test"
                    imageRef="http://localhost/images/1">
                    <metadata>
                        <meta key="My Server Name">Apache1</meta>
                    </metadata>
                    <personality>
                        <file path="/etc/banner.txt">Mg==</file>
                    </personality>
                </rebuild>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "rebuild": {
                "name": "new-server-test",
                "imageRef": "http://localhost/images/1",
                "metadata": {
                    "My Server Name": "Apache1",
                },
                "personality": [
                    {"path": "/etc/banner.txt", "contents": "Mg=="},
                ],
            },
        }
        self.assertDictMatch(request['body'], expected)

    def test_rebuild_minimum(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <rebuild
                    xmlns="http://docs.openstack.org/compute/api/v1.1"
                    imageRef="http://localhost/images/1"/>"""
        request = self.deserializer.deserialize(serial_request, 'action')
        expected = {
            "rebuild": {
                "imageRef": "http://localhost/images/1",
            },
        }
        self.assertDictMatch(request['body'], expected)

    def test_rebuild_no_imageRef(self):
        serial_request = """<?xml version="1.0" encoding="UTF-8"?>
                <rebuild
                    xmlns="http://docs.openstack.org/compute/api/v1.1"
                    name="new-server-test">
                    <metadata>
                        <meta key="My Server Name">Apache1</meta>
                    </metadata>
                    <personality>
                        <file path="/etc/banner.txt">Mg==</file>
                    </personality>
                </rebuild>"""
        self.assertRaises(AttributeError,
                          self.deserializer.deserialize,
                          serial_request,
                          'action')
