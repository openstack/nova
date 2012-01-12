# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import base64
import datetime

import mox
import stubout
import webob

from nova.api.openstack.v2 import servers
from nova.compute import vm_states
from nova.compute import instance_types
from nova import context
import nova.db
from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


FLAGS = flags.FLAGS
FAKE_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def return_server_by_id(context, id):
    return stub_instance(id)


def return_server_by_uuid(context, uuid):
    return stub_instance(1, uuid=uuid)


def return_server_by_uuid_not_found(context, uuid):
    raise exception.NotFound()


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
                  name=None, vm_state=None, task_state=None, uuid=None,
                  access_ip_v4="", access_ip_v6=""):
    if metadata is not None:
        metadata_items = [{'key':k, 'value':v} for k, v in metadata.items()]
    else:
        metadata_items = [{'key':'seq', 'value':id}]

    if uuid is None:
        uuid = FAKE_UUID

    inst_type = instance_types.get_instance_type_by_flavor_id(int(flavor_id))

    instance = {
        "id": int(id),
        "name": str(id),
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
        "access_ip_v4": access_ip_v4,
        "access_ip_v6": access_ip_v6,
        "uuid": uuid,
        "virtual_interfaces": [],
        "progress": 0,
    }

    instance["fixed_ips"] = [{"address": '192.168.0.1',
                              "network":
                                      {'label': 'public', 'cidr_v6': None},
                              "virtual_interface":
                                      {'address': 'aa:aa:aa:aa:aa:aa'},
                              "floating_ips": []}]

    return instance


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance, password):
        self.instance_id = instance['uuid']
        self.password = password


class ServerActionsControllerTest(test.TestCase):

    def setUp(self):
        self.maxDiff = None
        super(ServerActionsControllerTest, self).setUp()

        self.stubs = stubout.StubOutForTesting()
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db, 'instance_get', return_server_by_id)
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server_by_uuid)
        self.stubs.Set(nova.db, 'instance_update', instance_update)

        fakes.stub_out_glance(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.snapshot = fakes.stub_out_compute_api_snapshot(self.stubs)
        service_class = 'nova.image.glance.GlanceImageService'
        self.service = utils.import_object(service_class)
        self.context = context.RequestContext(1, None)
        self.service.delete_all()
        self.sent_to_glance = {}
        fakes.stub_out_glance_add_image(self.stubs, self.sent_to_glance)
        self.flags(allow_instance_snapshots=True)
        self.uuid = FAKE_UUID
        self.url = '/v2/fake/servers/%s/action' % self.uuid

        self.controller = servers.Controller()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(ServerActionsControllerTest, self).tearDown()

    def test_server_bad_body(self):
        body = {}

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_server_unknown_action(self):
        body = {'sockTheFox': {'fakekey': '1234'}}

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_server_change_password(self):
        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)
        body = {'changePassword': {'adminPass': '1234pass'}}

        req = fakes.HTTPRequest.blank(self.url)
        self.controller.action(req, FAKE_UUID, body)

        self.assertEqual(mock_method.instance_id, self.uuid)
        self.assertEqual(mock_method.password, '1234pass')

    def test_server_change_password_not_a_string(self):
        body = {'changePassword': {'adminPass': 1234}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_server_change_password_bad_request(self):
        body = {'changePassword': {'pass': '12345'}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_server_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_server_change_password_none(self):
        body = {'changePassword': {'adminPass': None}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_reboot_hard(self):
        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequest.blank(self.url)
        self.controller.action(req, FAKE_UUID, body)

    def test_reboot_soft(self):
        body = dict(reboot=dict(type="SOFT"))
        req = fakes.HTTPRequest.blank(self.url)
        self.controller.action(req, FAKE_UUID, body)

    def test_reboot_incorrect_type(self):
        body = dict(reboot=dict(type="NOT_A_TYPE"))
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_reboot_missing_type(self):
        body = dict(reboot=dict())
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_reboot_not_found(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_by_uuid_not_found)

        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.action,
                          req, str(utils.gen_uuid()), body)

    def test_reboot_raises_conflict_on_invalid_state(self):
        body = dict(reboot=dict(type="HARD"))

        def fake_reboot(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'reboot', fake_reboot)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.action,
                          req, FAKE_UUID, body)

    def test_rebuild_accepted_minimum(self):
        new_return_server = return_server_with_attributes(image_ref='2')
        self.stubs.Set(nova.db, 'instance_get', new_return_server)
        self_href = 'http://localhost/v2/fake/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        robj = self.controller.action(req, FAKE_UUID, body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(len(body['server']['adminPass']),
                         FLAGS.password_length)
        self.assertEqual(robj['location'], self_href)

    def test_rebuild_raises_conflict_on_invalid_state(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        def fake_rebuild(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'rebuild', fake_rebuild)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.action, req, FAKE_UUID, body)

    def test_rebuild_accepted_with_metadata(self):
        metadata = {'new': 'metadata'}

        new_return_server = return_server_with_attributes(metadata=metadata)
        self.stubs.Set(nova.db, 'instance_get', new_return_server)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "metadata": metadata,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller.action(req, FAKE_UUID, body).obj

        self.assertEqual(body['server']['metadata'], metadata)

    def test_rebuild_accepted_with_bad_metadata(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "metadata": "stack",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_rebuild_bad_entity(self):
        body = {
            "rebuild": {
                "imageId": 2,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_rebuild_bad_personality(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "personality": [{
                    "path": "/path/to/file",
                    "contents": "INVALID b64",
                }]
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_rebuild_personality(self):
        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "personality": [{
                    "path": "/path/to/file",
                    "contents": base64.b64encode("Test String"),
                }]
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller.action(req, FAKE_UUID, body).obj

        self.assertTrue('personality' not in body['server'])

    def test_rebuild_admin_pass(self):
        new_return_server = return_server_with_attributes(image_ref='2')
        self.stubs.Set(nova.db, 'instance_get', new_return_server)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "adminPass": "asdf",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller.action(req, FAKE_UUID, body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(body['server']['adminPass'], 'asdf')

    def test_rebuild_server_not_found(self):
        def server_not_found(self, instance_id):
            raise exception.InstanceNotFound(instance_id=instance_id)
        self.stubs.Set(nova.db, 'instance_get', server_not_found)

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.action, req, FAKE_UUID, body)

    def test_rebuild_accessIP(self):
        attributes = {
            'access_ip_v4': '172.19.0.1',
            'access_ip_v6': 'fe80::1',
        }

        body = {
            "rebuild": {
                "imageRef": "http://localhost/images/2",
                "accessIPv4": "172.19.0.1",
                "accessIPv6": "fe80::1",
            },
        }

        update = self.mox.CreateMockAnything()
        self.stubs.Set(nova.compute.API, 'update', update)
        req = fakes.HTTPRequest.blank(self.url)
        context = req.environ['nova.context']
        update(context, mox.IgnoreArg(),
                image_ref='http://localhost/images/2',
                vm_state=vm_states.REBUILDING,
                task_state=None, progress=0, **attributes).AndReturn(None)
        self.mox.ReplayAll()

        self.controller.action(req, FAKE_UUID, body)
        self.mox.VerifyAll()

    def test_resize_server(self):

        body = dict(resize=dict(flavorRef="http://localhost/3"))

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller.action(req, FAKE_UUID, body)

        self.assertEqual(self.resize_called, True)

    def test_resize_server_no_flavor(self):
        body = dict(resize=dict())

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_resize_server_no_flavor_ref(self):
        body = dict(resize=dict(flavorRef=None))

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_resize_raises_conflict_on_invalid_state(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        def fake_resize(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'resize', fake_resize)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.action,
                          req, FAKE_UUID, body)

    def test_confirm_resize_server(self):
        body = dict(confirmResize=None)

        self.confirm_resize_called = False

        def cr_mock(*args):
            self.confirm_resize_called = True

        self.stubs.Set(nova.compute.api.API, 'confirm_resize', cr_mock)

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller.action(req, FAKE_UUID, body)

        self.assertEqual(self.confirm_resize_called, True)

    def test_confirm_resize_migration_not_found(self):
        body = dict(confirmResize=None)

        def confirm_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stubs.Set(nova.compute.api.API,
                       'confirm_resize',
                       confirm_resize_mock)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_confirm_resize_raises_conflict_on_invalid_state(self):
        body = dict(confirmResize=None)

        def fake_confirm_resize(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'confirm_resize',
                fake_confirm_resize)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.action,
                          req, FAKE_UUID, body)

    def test_revert_resize_migration_not_found(self):
        body = dict(revertResize=None)

        def revert_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stubs.Set(nova.compute.api.API,
                       'revert_resize',
                       revert_resize_mock)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_revert_resize_server(self):
        body = dict(revertResize=None)

        self.revert_resize_called = False

        def revert_mock(*args):
            self.revert_resize_called = True

        self.stubs.Set(nova.compute.api.API, 'revert_resize', revert_mock)

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller.action(req, FAKE_UUID, body)

        self.assertEqual(self.revert_resize_called, True)

    def test_revert_resize_raises_conflict_on_invalid_state(self):
        body = dict(revertResize=None)

        def fake_revert_resize(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'revert_resize',
                fake_revert_resize)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.action,
                          req, FAKE_UUID, body)

    def test_create_image(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        response = self.controller.action(req, FAKE_UUID, body)

        location = response.headers['Location']
        self.assertEqual('http://localhost/v2/fake/images/123', location)
        server_location = self.snapshot.extra_props_last_call['instance_ref']
        expected_server_location = 'http://localhost/v2/servers/' + self.uuid
        self.assertEqual(expected_server_location, server_location)

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
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_create_image_with_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {'key': 'asdf'},
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        response = self.controller.action(req, FAKE_UUID, body)

        location = response.headers['Location']
        self.assertEqual('http://localhost/v2/fake/images/123', location)

    def test_create_image_with_too_much_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {},
            },
        }
        for num in range(FLAGS.quota_metadata_items + 1):
            body['createImage']['metadata']['foo%i' % num] = "bar"

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.action, req, FAKE_UUID, body)

    def test_create_image_no_name(self):
        body = {
            'createImage': {},
        }
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_create_image_bad_metadata(self):
        body = {
            'createImage': {
                'name': 'geoff',
                'metadata': 'henry',
            },
        }
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.action, req, FAKE_UUID, body)

    def test_create_image_raises_conflict_on_invalid_state(self):
        def snapshot(*args, **kwargs):
            raise exception.InstanceInvalidState
        self.stubs.Set(nova.compute.API, 'snapshot', snapshot)

        body = {
            "createImage": {
                "name": "test_snapshot",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.action, req, FAKE_UUID, body)


class TestServerActionXMLDeserializer(test.TestCase):

    def setUp(self):
        self.deserializer = servers.ActionDeserializer()

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
