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

import mox
import webob

from nova.api.openstack.compute import servers
from nova.compute import vm_states
import nova.db
from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


FLAGS = flags.FLAGS
FAKE_UUID = fakes.FAKE_UUID


def return_server_not_found(context, uuid):
    raise exception.NotFound()


def instance_update(context, instance_id, kwargs):
    return fakes.stub_instance(instance_id)


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance, password):
        self.instance_id = instance['uuid']
        self.password = password


class ServerActionsControllerTest(test.TestCase):

    def setUp(self):
        super(ServerActionsControllerTest, self).setUp()

        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                        host='fake_host'))
        self.stubs.Set(nova.db, 'instance_update', instance_update)

        fakes.stub_out_glance(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        fakes.stub_out_image_service(self.stubs)
        service_class = 'nova.image.glance.GlanceImageService'
        self.service = utils.import_object(service_class)
        self.service.delete_all()
        self.sent_to_glance = {}
        fakes.stub_out_glance_add_image(self.stubs, self.sent_to_glance)
        self.flags(allow_instance_snapshots=True,
                   enable_instance_password=True)
        self.uuid = FAKE_UUID
        self.url = '/v2/fake/servers/%s/action' % self.uuid
        self._image_href = '155d900f-4e14-4e4c-a73d-069cbf4541e6'

        self.controller = servers.Controller()

    def test_server_change_password(self):
        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)
        body = {'changePassword': {'adminPass': '1234pass'}}

        req = fakes.HTTPRequest.blank(self.url)
        self.controller._action_change_password(req, FAKE_UUID, body)

        self.assertEqual(mock_method.instance_id, self.uuid)
        self.assertEqual(mock_method.password, '1234pass')

    def test_server_change_password_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False)

        mock_method = MockSetAdminPassword()
        self.stubs.Set(nova.compute.api.API, 'set_admin_password', mock_method)
        body = {'changePassword': {'adminPass': '1234pass'}}

        req = fakes.HTTPRequest.blank(self.url)
        self.controller._action_change_password(req, FAKE_UUID, body)

        self.assertEqual(mock_method.instance_id, self.uuid)
        # note,the mock still contains the password.
        self.assertEqual(mock_method.password, '1234pass')

    def test_server_change_password_not_a_string(self):
        body = {'changePassword': {'adminPass': 1234}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_change_password,
                          req, FAKE_UUID, body)

    def test_server_change_password_bad_request(self):
        body = {'changePassword': {'pass': '12345'}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_change_password,
                          req, FAKE_UUID, body)

    def test_server_change_password_empty_string(self):
        body = {'changePassword': {'adminPass': ''}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_change_password,
                          req, FAKE_UUID, body)

    def test_server_change_password_none(self):
        body = {'changePassword': {'adminPass': None}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_change_password,
                          req, FAKE_UUID, body)

    def test_reboot_hard(self):
        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequest.blank(self.url)
        self.controller._action_reboot(req, FAKE_UUID, body)

    def test_reboot_soft(self):
        body = dict(reboot=dict(type="SOFT"))
        req = fakes.HTTPRequest.blank(self.url)
        self.controller._action_reboot(req, FAKE_UUID, body)

    def test_reboot_incorrect_type(self):
        body = dict(reboot=dict(type="NOT_A_TYPE"))
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_missing_type(self):
        body = dict(reboot=dict())
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_not_found(self):
        self.stubs.Set(nova.db, 'instance_get_by_uuid',
                       return_server_not_found)

        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_reboot,
                          req, str(utils.gen_uuid()), body)

    def test_reboot_raises_conflict_on_invalid_state(self):
        body = dict(reboot=dict(type="HARD"))

        def fake_reboot(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'reboot', fake_reboot)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_rebuild_accepted_minimum(self):
        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server)
        self_href = 'http://localhost/v2/fake/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        robj = self.controller._action_rebuild(req, FAKE_UUID, body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(len(body['server']['adminPass']),
                         FLAGS.password_length)

        self.assertEqual(robj['location'], self_href)

    def test_rebuild_accepted_minimum_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False)

        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server)
        self_href = 'http://localhost/v2/fake/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        robj = self.controller._action_rebuild(req, FAKE_UUID, body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertTrue("adminPass" not in body['server'])

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
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body)

    def test_rebuild_accepted_with_metadata(self):
        metadata = {'new': 'metadata'}

        return_server = fakes.fake_instance_get(metadata=metadata,
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": metadata,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body).obj

        self.assertEqual(body['server']['metadata'], metadata)

    def test_rebuild_accepted_with_bad_metadata(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": "stack",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body)

    def test_rebuild_bad_entity(self):
        body = {
            "rebuild": {
                "imageId": self._image_href,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body)

    def test_rebuild_bad_personality(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "personality": [{
                    "path": "/path/to/file",
                    "contents": "INVALID b64",
                }]
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body)

    def test_rebuild_personality(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "personality": [{
                    "path": "/path/to/file",
                    "contents": base64.b64encode("Test String"),
                }]
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body).obj

        self.assertTrue('personality' not in body['server'])

    def test_rebuild_admin_pass(self):
        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "adminPass": "asdf",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(body['server']['adminPass'], 'asdf')

    def test_rebuild_admin_pass_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False)

        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(nova.db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "adminPass": "asdf",
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertTrue('adminPass' not in body['server'])

    def test_rebuild_server_not_found(self):
        def server_not_found(self, instance_id):
            raise exception.InstanceNotFound(instance_id=instance_id)
        self.stubs.Set(nova.db, 'instance_get_by_uuid', server_not_found)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body)

    def test_rebuild_with_bad_image(self):
        body = {
            "rebuild": {
                "imageRef": "foo",
            },
        }
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body)

    def test_rebuild_accessIP(self):
        attributes = {
            'access_ip_v4': '172.19.0.1',
            'access_ip_v6': 'fe80::1',
        }

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "accessIPv4": "172.19.0.1",
                "accessIPv6": "fe80::1",
            },
        }

        update = self.mox.CreateMockAnything()
        self.stubs.Set(nova.compute.API, 'update', update)
        req = fakes.HTTPRequest.blank(self.url)
        context = req.environ['nova.context']
        update(context, mox.IgnoreArg(),
                image_ref=self._image_href,
                vm_state=vm_states.REBUILDING,
                task_state=None, progress=0, **attributes).AndReturn(None)
        self.mox.ReplayAll()

        self.controller._action_rebuild(req, FAKE_UUID, body)

    def test_resize_server(self):

        body = dict(resize=dict(flavorRef="http://localhost/3"))

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(nova.compute.api.API, 'resize', resize_mock)

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_resize(req, FAKE_UUID, body)

        self.assertEqual(self.resize_called, True)

    def test_resize_server_no_flavor(self):
        body = dict(resize=dict())

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          req, FAKE_UUID, body)

    def test_resize_server_no_flavor_ref(self):
        body = dict(resize=dict(flavorRef=None))

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          req, FAKE_UUID, body)

    def test_resize_raises_conflict_on_invalid_state(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        def fake_resize(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'resize', fake_resize)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_resize,
                          req, FAKE_UUID, body)

    def test_confirm_resize_server(self):
        body = dict(confirmResize=None)

        self.confirm_resize_called = False

        def cr_mock(*args):
            self.confirm_resize_called = True

        self.stubs.Set(nova.compute.api.API, 'confirm_resize', cr_mock)

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_confirm_resize(req, FAKE_UUID, body)

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
                          self.controller._action_confirm_resize,
                          req, FAKE_UUID, body)

    def test_confirm_resize_raises_conflict_on_invalid_state(self):
        body = dict(confirmResize=None)

        def fake_confirm_resize(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'confirm_resize',
                fake_confirm_resize)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_confirm_resize,
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
                          self.controller._action_revert_resize,
                          req, FAKE_UUID, body)

    def test_revert_resize_server(self):
        body = dict(revertResize=None)

        self.revert_resize_called = False

        def revert_mock(*args):
            self.revert_resize_called = True

        self.stubs.Set(nova.compute.api.API, 'revert_resize', revert_mock)

        req = fakes.HTTPRequest.blank(self.url)
        body = self.controller._action_revert_resize(req, FAKE_UUID, body)

        self.assertEqual(self.revert_resize_called, True)

    def test_revert_resize_raises_conflict_on_invalid_state(self):
        body = dict(revertResize=None)

        def fake_revert_resize(*args, **kwargs):
            raise exception.InstanceInvalidState

        self.stubs.Set(nova.compute.api.API, 'revert_resize',
                fake_revert_resize)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_revert_resize,
                          req, FAKE_UUID, body)

    def test_create_image(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        response = self.controller._action_create_image(req, FAKE_UUID, body)

        location = response.headers['Location']
        self.assertEqual('http://localhost/v2/fake/images/123', location)

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
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_with_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {'key': 'asdf'},
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        response = self.controller._action_create_image(req, FAKE_UUID, body)

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
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_no_name(self):
        body = {
            'createImage': {},
        }
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_blank_name(self):
        body = {
            'createImage': {
                'name': '',
            }
        }
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_bad_metadata(self):
        body = {
            'createImage': {
                'name': 'geoff',
                'metadata': 'henry',
            },
        }
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

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
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)


class TestServerActionXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerActionXMLDeserializer, self).setUp()
        self.deserializer = servers.ActionDeserializer()

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
