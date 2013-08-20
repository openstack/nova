# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 OpenStack Foundation
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
import uuid

from oslo.config import cfg

from nova.api.openstack import compute
from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import servers
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import db
import nova.db.api
from nova.network import manager
from nova.openstack.common import jsonutils
from nova.openstack.common import rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests.image import fake


CONF = cfg.CONF
FAKE_UUID = fakes.FAKE_UUID


def fake_gen_uuid():
    return FAKE_UUID


def return_security_group(context, instance_id, security_group_id):
    pass


class SchedulerHintsTestCase(test.TestCase):

    def setUp(self):
        super(SchedulerHintsTestCase, self).setUp()
        self.fake_instance = fakes.stub_instance(1, uuid=FAKE_UUID)
        self.app = compute.APIRouterV3(init_only=('servers',
                                                  'os-scheduler-hints'))

    def test_create_server_without_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {})
            return ([self.fake_instance], '')

        self.stubs.Set(nova.compute.api.API, 'create', fake_create)

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavor_ref': '1',
               }}

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def test_create_server_with_hints(self):

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], {'a': 'b'})
            return ([self.fake_instance], '')

        self.stubs.Set(nova.compute.api.API, 'create', fake_create)

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavor_ref': '1',
            },
            'os-scheduler-hints:scheduler_hints': {'a': 'b'},
        }

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(202, res.status_int)

    def test_create_server_bad_hints(self):
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {
            'server': {
                  'name': 'server_test',
                  'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavor_ref': '1',
            },
            'os-scheduler-hints:scheduler_hints': 'here',
        }

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)


class ServersControllerCreateTest(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)
        CONF.set_override('extensions_blacklist', 'os-scheduler-hints',
                          'osapi_v3')
        self.no_scheduler_hints_controller = servers.ServersController(
            extension_info=ext_info)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "config_drive": None,
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "root_device_name": inst.get('root_device_name', 'vda'),
            })

            self.instance_cache_by_id[instance['id']] = instance
            self.instance_cache_by_uuid[instance['uuid']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def rpc_call_wrapper(context, topic, msg, timeout=None):
            """Stub out the scheduler creating the instance entry."""
            if (topic == CONF.scheduler_topic and
                    msg['method'] == 'run_instance'):
                request_spec = msg['args']['request_spec']
                num_instances = request_spec.get('num_instances', 1)
                instances = []
                for x in xrange(num_instances):
                    instances.append(instance_create(context,
                        request_spec['instance_properties']))
                return instances

        def server_update(context, instance_uuid, params):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(uuid, 'uuid4', fake_gen_uuid)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(db, 'instance_create', instance_create)
        self.stubs.Set(db, 'instance_system_metadata_update',
                fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(rpc, 'cast', fake_method)
        self.stubs.Set(rpc, 'call', rpc_call_wrapper)
        self.stubs.Set(db, 'instance_update_and_get_original',
                server_update)
        self.stubs.Set(rpc, 'queue_get_for', queue_get_for)
        self.stubs.Set(manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)

    def _test_create_extra(self, params, no_image=False,
                           override_controller=None):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', image_ref=image_uuid, flavor_ref=2)
        if no_image:
            server.pop('image_ref', None)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        if override_controller:
            server = override_controller.create(req, body).obj['server']
        else:
            server = self.controller.create(req, body).obj['server']

    def test_create_instance_with_scheduler_hints_disabled(self):
        hints = {'a': 'b'}
        params = {'scheduler_hints': hints}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('scheduler_hints', kwargs)
            #            self.assertEqual(kwargs['scheduler_hints'], {})
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params,
                override_controller=self.no_scheduler_hints_controller)

    def test_create_instance_with_scheduler_hints_enabled(self):
        hints = {'a': 'b'}
        params = {'scheduler_hints': hints}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], hints)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)


class TestServerCreateRequestXMLDeserializer(test.TestCase):

    def setUp(self):
        super(TestServerCreateRequestXMLDeserializer, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        controller = servers.ServersController(extension_info=ext_info)
        self.deserializer = servers.CreateDeserializer(controller)

    def test_request_with_scheduler_hints_and_alternate_namespace_prefix(self):
        serial_request = """
<ns2:server xmlns:ns2="http://docs.openstack.org/compute/api/v3"
     name="new-server-test"
     image_ref="1"
     flavor_ref="2">
     <ns2:metadata><ns2:meta key="hello">world</ns2:meta></ns2:metadata>
     <os:scheduler_hints
     xmlns:os="http://docs.openstack.org/compute/ext/scheduler-hints/api/v3">
             <hypervisor>xen</hypervisor>
             <near>eb999657-dd6b-464e-8713-95c532ac3b18</near>
     </os:scheduler_hints>
     </ns2:server>
        """
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "server": {
                'os-scheduler-hints:scheduler_hints': {
                    'hypervisor': ['xen'],
                    'near': ['eb999657-dd6b-464e-8713-95c532ac3b18']
                },
                "name": "new-server-test",
                "image_ref": "1",
                "flavor_ref": "2",
                "metadata": {
                    "hello": "world"
                }
            }
        }
        self.assertEquals(request['body'], expected)
