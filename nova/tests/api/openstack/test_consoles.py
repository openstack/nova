# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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
import json
import webob

from nova.api.openstack import consoles
from nova import console
from nova import db
from nova.compute import vm_states
from nova import exception
from nova import flags
from nova import test
from nova.tests.api.openstack import common
from nova.tests.api.openstack import fakes
from nova import utils


FLAGS = flags.FLAGS
FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def return_server_by_id(context, id):
    print "GOT HERE"
    return stub_instance(id)


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
        "uuid": FAKE_UUID,
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
        "local_gb": 0,
        "hostname": "",
        "host": host,
        "instance_type": {},
        "user_data": "",
        "reservation_id": reservation_id,
        "mac_address": "",
        "scheduled_at": utils.utcnow(),
        "launched_at": utils.utcnow(),
        "terminated_at": utils.utcnow(),
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


class ConsolesTest(test.TestCase):
    def setUp(self):
        super(ConsolesTest, self).setUp()
        self.flags(verbose=True)
        self.stubs.Set(db.api, 'instance_get', return_server_by_id)
        self.webreq = common.webob_factory('/v1.0/servers')

    def test_create_console(self):
        def fake_create_console(cons_self, context, instance_id):
            self.assertTrue(instance_id, 10)
            return {}
        self.stubs.Set(console.API, 'create_console', fake_create_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles')
        req.method = "POST"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)

    def test_show_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, 10)
            self.assertEqual(console_id, 20)
            pool = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            return dict(id=console_id, password='fake_password',
                    port='fake_port', pool=pool)

        expected = {'console': {'id': 20,
                                'port': 'fake_port',
                                'host': 'fake_hostname',
                                'password': 'fake_password',
                                'console_type': 'fake_type'}}

        self.stubs.Set(console.API, 'get_console', fake_get_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles/20')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertDictMatch(res_dict, expected)

    def test_show_console_unknown_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFound(console_id=console_id)

        self.stubs.Set(console.API, 'get_console', fake_get_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles/20')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_show_console_unknown_instance(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            raise exception.InstanceNotFound(instance_id=instance_id)

        self.stubs.Set(console.API, 'get_console', fake_get_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles/20')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_list_consoles(self):
        def fake_get_consoles(cons_self, context, instance_id):
            self.assertEqual(instance_id, 10)

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

        self.stubs.Set(console.API, 'get_consoles', fake_get_consoles)

        req = webob.Request.blank('/v1.0/servers/10/consoles')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        self.assertDictMatch(res_dict, expected)

    def test_delete_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, 10)
            self.assertEqual(console_id, 20)
            pool = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            return dict(id=console_id, password='fake_password',
                    port='fake_port', pool=pool)

        def fake_delete_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, 10)
            self.assertEqual(console_id, 20)

        self.stubs.Set(console.API, 'get_console', fake_get_console)
        self.stubs.Set(console.API, 'delete_console', fake_delete_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles/20')
        req.method = "DELETE"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_show_console_unknown_console(self):
        def fake_delete_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFound(console_id=console_id)

        self.stubs.Set(console.API, 'delete_console', fake_delete_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles/20')
        req.method = "DELETE"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_show_console_unknown_instance(self):
        def fake_delete_console(cons_self, context, instance_id, console_id):
            raise exception.InstanceNotFound(instance_id=instance_id)

        self.stubs.Set(console.API, 'delete_console', fake_delete_console)

        req = webob.Request.blank('/v1.0/servers/10/consoles/20')
        req.method = "DELETE"
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)
