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

from oslo_serialization import jsonutils

from nova import exception
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3, task_state="kayaking",
            vm_state="slightly crunchy", power_state=1)
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_all(*args, **kwargs):
    db_list = [
        fakes.stub_instance(1, uuid=UUID1, task_state="task-1",
                vm_state="vm-1", power_state=1),
        fakes.stub_instance(2, uuid=UUID2, task_state="task-2",
                vm_state="vm-2", power_state=2),
    ]

    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            objects.InstanceList(),
                                            db_list, fields)


class ExtendedStatusTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-STS:'
    fake_url = '/v2/fake'

    def _set_flags(self):
        pass

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app_v21())
        return res

    def setUp(self):
        super(ExtendedStatusTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        self.stub_out('nova.compute.api.API.get_all', fake_compute_get_all)
        self._set_flags()
        return_server = fakes.fake_instance_get()
        self.stub_out('nova.db.api.instance_get_by_uuid', return_server)

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def assertServerStates(self, server, vm_state, power_state, task_state):
        self.assertEqual(server.get('%svm_state' % self.prefix), vm_state)
        self.assertEqual(int(server.get('%spower_state' % self.prefix)),
                         power_state)
        self.assertEqual(server.get('%stask_state' % self.prefix), task_state)

    def test_show(self):
        url = self.fake_url + '/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerStates(self._get_server(res.body),
                                vm_state='slightly crunchy',
                                power_state=1,
                                task_state='kayaking')

    def test_detail(self):
        url = self.fake_url + '/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertServerStates(server,
                                    vm_state='vm-%s' % (i + 1),
                                    power_state=(i + 1),
                                    task_state='task-%s' % (i + 1))

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        url = self.fake_url + '/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)
