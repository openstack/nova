# Copyright 2010-2011 OpenStack Foundation
# Copyright 2011 Piston Cloud Computing, Inc.
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

import datetime

from oslo_policy import policy as oslo_policy
from oslo_utils import timeutils
import webob

from nova.api.openstack.compute import consoles as consoles_v21
from nova.compute import vm_states
from nova import exception
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers
from nova.tests import uuidsentinel as uuids


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


class FakeInstanceDB(object):

    def __init__(self):
        self.instances_by_id = {}
        self.ids_by_uuid = {}
        self.max_id = 0

    def return_server_by_id(self, context, id):
        if id not in self.instances_by_id:
            self._add_server(id=id)
        return dict(self.instances_by_id[id])

    def return_server_by_uuid(self, context, uuid):
        if uuid not in self.ids_by_uuid:
            self._add_server(uuid=uuid)
        return dict(self.instances_by_id[self.ids_by_uuid[uuid]])

    def _add_server(self, id=None, uuid=None):
        if id is None:
            id = self.max_id + 1
        if uuid is None:
            uuid = uuids.fake
        instance = stub_instance(id, uuid=uuid)
        self.instances_by_id[id] = instance
        self.ids_by_uuid[uuid] = id
        if id > self.max_id:
            self.max_id = id


def stub_instance(id, user_id='fake', project_id='fake', host=None,
                  vm_state=None, task_state=None,
                  reservation_id="", uuid=FAKE_UUID, image_ref="10",
                  flavor_id="1", name=None, key_name='',
                  access_ipv4=None, access_ipv6=None, progress=0):

    if host is not None:
        host = str(host)

    if key_name:
        key_data = 'FAKE'
    else:
        key_data = ''

    # ReservationID isn't sent back, hack it in there.
    server_name = name or "server%s" % id
    if reservation_id != "":
        server_name = "reservation_%s" % (reservation_id, )

    instance = {
        "id": int(id),
        "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
        "admin_pass": "",
        "user_id": user_id,
        "project_id": project_id,
        "image_ref": image_ref,
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": key_name,
        "key_data": key_data,
        "vm_state": vm_state or vm_states.BUILDING,
        "task_state": task_state,
        "memory_mb": 0,
        "vcpus": 0,
        "root_gb": 0,
        "hostname": "",
        "host": host,
        "instance_type": {},
        "user_data": "",
        "reservation_id": reservation_id,
        "mac_address": "",
        "launched_at": timeutils.utcnow(),
        "terminated_at": timeutils.utcnow(),
        "availability_zone": "",
        "display_name": server_name,
        "display_description": "",
        "locked": False,
        "metadata": [],
        "access_ip_v4": access_ipv4,
        "access_ip_v6": access_ipv6,
        "uuid": uuid,
        "progress": progress}

    return instance


class ConsolesControllerTestV21(test.NoDBTestCase):
    def setUp(self):
        super(ConsolesControllerTestV21, self).setUp()
        self.instance_db = FakeInstanceDB()
        self.stub_out('nova.db.instance_get',
                      self.instance_db.return_server_by_id)
        self.stub_out('nova.db.instance_get_by_uuid',
                      self.instance_db.return_server_by_uuid)
        self.uuid = uuids.fake
        self.url = '/v2/fake/servers/%s/consoles' % self.uuid
        self._set_up_controller()

    def _set_up_controller(self):
        self.controller = consoles_v21.ConsolesController()

    def test_create_console(self):
        def fake_create_console(cons_self, context, instance_id):
            self.assertEqual(instance_id, self.uuid)
            return {}

        self.stub_out('nova.console.api.API.create_console',
                      fake_create_console)

        req = fakes.HTTPRequest.blank(self.url)
        self.controller.create(req, self.uuid, None)

    def test_create_console_unknown_instance(self):
        def fake_create_console(cons_self, context, instance_id):
            raise exception.InstanceNotFound(instance_id=instance_id)

        self.stub_out('nova.console.api.API.create_console',
                      fake_create_console)

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, self.uuid, None)

    def test_show_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, self.uuid)
            self.assertEqual(console_id, 20)
            pool = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            return dict(id=console_id, password='fake_password',
                    port='fake_port', pool=pool, instance_name='inst-0001')

        expected = {'console': {'id': 20,
                                'port': 'fake_port',
                                'host': 'fake_hostname',
                                'password': 'fake_password',
                                'instance_name': 'inst-0001',
                                'console_type': 'fake_type'}}

        self.stub_out('nova.console.api.API.get_console', fake_get_console)

        req = fakes.HTTPRequest.blank(self.url + '/20')
        res_dict = self.controller.show(req, self.uuid, '20')
        self.assertThat(res_dict, matchers.DictMatches(expected))

    def test_show_console_unknown_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFound(console_id=console_id)

        self.stub_out('nova.console.api.API.get_console', fake_get_console)

        req = fakes.HTTPRequest.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, self.uuid, '20')

    def test_show_console_unknown_instance(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFoundForInstance(
                instance_uuid=instance_id)

        self.stub_out('nova.console.api.API.get_console', fake_get_console)

        req = fakes.HTTPRequest.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, self.uuid, '20')

    def test_list_consoles(self):
        def fake_get_consoles(cons_self, context, instance_id):
            self.assertEqual(instance_id, self.uuid)

            pool1 = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            cons1 = dict(id=10, password='fake_password',
                    port='fake_port', pool=pool1)
            pool2 = dict(console_type='fake_type2',
                    public_hostname='fake_hostname2')
            cons2 = dict(id=11, password='fake_password2',
                    port='fake_port2', pool=pool2)
            return [cons1, cons2]

        expected = {'consoles':
                [{'console': {'id': 10, 'console_type': 'fake_type'}},
                 {'console': {'id': 11, 'console_type': 'fake_type2'}}]}

        self.stub_out('nova.console.api.API.get_consoles', fake_get_consoles)

        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.index(req, self.uuid)
        self.assertThat(res_dict, matchers.DictMatches(expected))

    def test_delete_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, self.uuid)
            self.assertEqual(console_id, 20)
            pool = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            return dict(id=console_id, password='fake_password',
                    port='fake_port', pool=pool)

        def fake_delete_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, self.uuid)
            self.assertEqual(console_id, 20)

        self.stub_out('nova.console.api.API.get_console', fake_get_console)
        self.stub_out('nova.console.api.API.delete_console',
                      fake_delete_console)

        req = fakes.HTTPRequest.blank(self.url + '/20')
        self.controller.delete(req, self.uuid, '20')

    def test_delete_console_unknown_console(self):
        def fake_delete_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFound(console_id=console_id)

        self.stub_out('nova.console.api.API.delete_console',
                      fake_delete_console)

        req = fakes.HTTPRequest.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.uuid, '20')

    def test_delete_console_unknown_instance(self):
        def fake_delete_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFoundForInstance(
                instance_uuid=instance_id)

        self.stub_out('nova.console.api.API.delete_console',
                      fake_delete_console)

        req = fakes.HTTPRequest.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.uuid, '20')

    def _test_fail_policy(self, rule, action, data=None):
        rules = {
            rule: "!",
        }

        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        req = fakes.HTTPRequest.blank(self.url + '/20')

        if data is not None:
            self.assertRaises(exception.PolicyNotAuthorized, action,
                              req, self.uuid, data)
        else:
            self.assertRaises(exception.PolicyNotAuthorized, action,
                              req, self.uuid)

    def test_delete_console_fail_policy(self):
        self._test_fail_policy("os_compute_api:os-consoles:delete",
                               self.controller.delete, data='20')

    def test_create_console_fail_policy(self):
        self._test_fail_policy("os_compute_api:os-consoles:create",
                               self.controller.create, data='20')

    def test_index_console_fail_policy(self):
        self._test_fail_policy("os_compute_api:os-consoles:index",
                               self.controller.index)

    def test_show_console_fail_policy(self):
        self._test_fail_policy("os_compute_api:os-consoles:show",
                               self.controller.show, data='20')
