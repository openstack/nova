# Copyright (c) 2011 Openstack, LLC.
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

from lxml import etree
import webob.exc

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova.api.openstack.compute.contrib import hosts as os_hosts
from nova.compute import power_state
from nova.compute import vm_states
from nova.scheduler import api as scheduler_api


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.hosts')
# Simulate the hosts returned by the zone manager.
HOST_LIST = [
        {"host_name": "host_c1", "service": "compute"},
        {"host_name": "host_c2", "service": "compute"},
        {"host_name": "host_v1", "service": "volume"},
        {"host_name": "host_v2", "service": "volume"}]


def stub_get_host_list(req):
    return HOST_LIST


def stub_set_host_enabled(context, host, enabled):
    # We'll simulate success and failure by assuming
    # that 'host_c1' always succeeds, and 'host_c2'
    # always fails
    fail = (host == "host_c2")
    status = "enabled" if (enabled ^ fail) else "disabled"
    return status


def stub_host_power_action(context, host, action):
    return action


def _create_instance(**kwargs):
    """Create a test instance"""
    ctxt = context.get_admin_context()
    return db.instance_create(ctxt, _create_instance_dict(**kwargs))


def _create_instance_dict(**kwargs):
    """Create a dictionary for a test instance"""
    inst = {}
    inst['image_ref'] = 'cedef40a-ed67-4d10-800e-17455edce175'
    inst['reservation_id'] = 'r-fakeres'
    inst['user_id'] = kwargs.get('user_id', 'admin')
    inst['project_id'] = kwargs.get('project_id', 'fake')
    inst['instance_type_id'] = '1'
    if 'host' in kwargs:
        inst['host'] = kwargs.get('host')
    inst['vcpus'] = kwargs.get('vcpus', 1)
    inst['memory_mb'] = kwargs.get('memory_mb', 20)
    inst['root_gb'] = kwargs.get('root_gb', 30)
    inst['ephemeral_gb'] = kwargs.get('ephemeral_gb', 30)
    inst['vm_state'] = kwargs.get('vm_state', vm_states.ACTIVE)
    inst['power_state'] = kwargs.get('power_state', power_state.RUNNING)
    inst['task_state'] = kwargs.get('task_state', None)
    inst['availability_zone'] = kwargs.get('availability_zone', None)
    inst['ami_launch_index'] = 0
    inst['launched_on'] = kwargs.get('launched_on', 'dummy')
    return inst


class FakeRequest(object):
    environ = {"nova.context": context.get_admin_context()}


class HostTestCase(test.TestCase):
    """Test Case for hosts."""

    def setUp(self):
        super(HostTestCase, self).setUp()
        self.controller = os_hosts.HostController()
        self.req = FakeRequest()
        self.stubs.Set(scheduler_api, 'get_host_list', stub_get_host_list)
        self.stubs.Set(self.controller.compute_api, 'set_host_enabled',
                stub_set_host_enabled)
        self.stubs.Set(self.controller.compute_api, 'host_power_action',
                stub_host_power_action)

    def test_list_hosts(self):
        """Verify that the compute hosts are returned."""
        hosts = os_hosts._list_hosts(self.req)
        self.assertEqual(hosts, HOST_LIST)

        compute_hosts = os_hosts._list_hosts(self.req, "compute")
        expected = [host for host in HOST_LIST
                if host["service"] == "compute"]
        self.assertEqual(compute_hosts, expected)

    def test_disable_host(self):
        dis_body = {"status": "disable"}
        result_c1 = self.controller.update(self.req, "host_c1", body=dis_body)
        self.assertEqual(result_c1["status"], "disabled")
        result_c2 = self.controller.update(self.req, "host_c2", body=dis_body)
        self.assertEqual(result_c2["status"], "enabled")

    def test_enable_host(self):
        en_body = {"status": "enable"}
        result_c1 = self.controller.update(self.req, "host_c1", body=en_body)
        self.assertEqual(result_c1["status"], "enabled")
        result_c2 = self.controller.update(self.req, "host_c2", body=en_body)
        self.assertEqual(result_c2["status"], "disabled")

    def test_enable_maintainance_mode(self):
        body = {"maintenance_mode": "enable"}
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.controller.update,
                          self.req, "host_c1", body=body)

    def test_disable_maintainance_mode_and_enable(self):
        body = {"status": "enable", "maintenance_mode": "disable"}
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.controller.update,
                          self.req, "host_c1", body=body)

    def test_host_startup(self):
        result = self.controller.startup(self.req, "host_c1")
        self.assertEqual(result["power_action"], "startup")

    def test_host_shutdown(self):
        result = self.controller.shutdown(self.req, "host_c1")
        self.assertEqual(result["power_action"], "shutdown")

    def test_host_reboot(self):
        result = self.controller.reboot(self.req, "host_c1")
        self.assertEqual(result["power_action"], "reboot")

    def test_bad_status_value(self):
        bad_body = {"status": "bad"}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                self.req, "host_c1", body=bad_body)

    def test_bad_update_key(self):
        bad_body = {"crazy": "bad"}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                self.req, "host_c1", body=bad_body)

    def test_bad_update_key_and_correct_udpate_key(self):
        bad_body = {"status": "disable", "crazy": "bad"}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                self.req, "host_c1", body=bad_body)

    def test_bad_host(self):
        self.assertRaises(exception.HostNotFound, self.controller.update,
                self.req, "bogus_host_name", body={"status": "disable"})

    def test_show_forbidden(self):
        self.req.environ["nova.context"].is_admin = False
        dest = 'dummydest'
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.show,
                          self.req, dest)
        self.req.environ["nova.context"].is_admin = True

    def test_show_host_not_exist(self):
        """A host given as an argument does not exists."""
        self.req.environ["nova.context"].is_admin = True
        dest = 'dummydest'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show,
                          self.req, dest)

    def _create_compute_service(self):
        """Create compute-manager(ComputeNode and Service record)."""
        ctxt = context.get_admin_context()
        dic = {'host': 'dummy', 'binary': 'nova-compute', 'topic': 'compute',
               'report_count': 0, 'availability_zone': 'dummyzone'}
        s_ref = db.service_create(ctxt, dic)

        dic = {'service_id': s_ref['id'],
               'vcpus': 16, 'memory_mb': 32, 'local_gb': 100,
               'vcpus_used': 16, 'memory_mb_used': 32, 'local_gb_used': 10,
               'hypervisor_type': 'qemu', 'hypervisor_version': 12003,
               'cpu_info': ''}
        db.compute_node_create(ctxt, dic)

        return db.service_get(ctxt, s_ref['id'])

    def test_show_no_project(self):
        """No instance are running on the given host."""
        ctxt = context.get_admin_context()
        s_ref = self._create_compute_service()

        result = self.controller.show(self.req, s_ref['host'])

        proj = ['(total)', '(used_now)', '(used_max)']
        column = ['host', 'project', 'cpu', 'memory_mb', 'disk_gb']
        self.assertEqual(len(result['host']), 3)
        for resource in result['host']:
            self.assertTrue(resource['resource']['project'] in proj)
            self.assertEqual(len(resource['resource']), 5)
            self.assertTrue(set(resource['resource'].keys()) == set(column))
        db.service_destroy(ctxt, s_ref['id'])

    def test_show_works_correctly(self):
        """show() works correctly as expected."""
        ctxt = context.get_admin_context()
        s_ref = self._create_compute_service()
        i_ref1 = _create_instance(project_id='p-01', host=s_ref['host'])
        i_ref2 = _create_instance(project_id='p-02', vcpus=3,
                                       host=s_ref['host'])

        result = self.controller.show(self.req, s_ref['host'])

        proj = ['(total)', '(used_now)', '(used_max)', 'p-01', 'p-02']
        column = ['host', 'project', 'cpu', 'memory_mb', 'disk_gb']
        self.assertEqual(len(result['host']), 5)
        for resource in result['host']:
            self.assertTrue(resource['resource']['project'] in proj)
            self.assertEqual(len(resource['resource']), 5)
            self.assertTrue(set(resource['resource'].keys()) == set(column))
        db.service_destroy(ctxt, s_ref['id'])
        db.instance_destroy(ctxt, i_ref1['id'])
        db.instance_destroy(ctxt, i_ref2['id'])


class HostSerializerTest(test.TestCase):
    def setUp(self):
        super(HostSerializerTest, self).setUp()
        self.deserializer = os_hosts.HostDeserializer()

    def test_index_serializer(self):
        serializer = os_hosts.HostIndexTemplate()
        text = serializer.serialize(HOST_LIST)

        tree = etree.fromstring(text)

        self.assertEqual('hosts', tree.tag)
        self.assertEqual(len(HOST_LIST), len(tree))
        for i in range(len(HOST_LIST)):
            self.assertEqual('host', tree[i].tag)
            self.assertEqual(HOST_LIST[i]['host_name'],
                             tree[i].get('host_name'))
            self.assertEqual(HOST_LIST[i]['service'],
                             tree[i].get('service'))

    def test_update_serializer_with_status(self):
        exemplar = dict(host='host_c1', status='enabled')
        serializer = os_hosts.HostUpdateTemplate()
        text = serializer.serialize(exemplar)

        tree = etree.fromstring(text)

        self.assertEqual('host', tree.tag)
        for key, value in exemplar.items():
            self.assertEqual(value, tree.get(key))

    def test_update_serializer_with_maintainance_mode(self):
        exemplar = dict(host='host_c1', maintenance_mode='enabled')
        serializer = os_hosts.HostUpdateTemplate()
        text = serializer.serialize(exemplar)

        tree = etree.fromstring(text)

        self.assertEqual('host', tree.tag)
        for key, value in exemplar.items():
            self.assertEqual(value, tree.get(key))

    def test_update_serializer_with_maintainance_mode_and_status(self):
        exemplar = dict(host='host_c1',
                        maintenance_mode='enabled',
                        status='enabled')
        serializer = os_hosts.HostUpdateTemplate()
        text = serializer.serialize(exemplar)

        tree = etree.fromstring(text)

        self.assertEqual('host', tree.tag)
        for key, value in exemplar.items():
            self.assertEqual(value, tree.get(key))

    def test_action_serializer(self):
        exemplar = dict(host='host_c1', power_action='reboot')
        serializer = os_hosts.HostActionTemplate()
        text = serializer.serialize(exemplar)

        tree = etree.fromstring(text)

        self.assertEqual('host', tree.tag)
        for key, value in exemplar.items():
            self.assertEqual(value, tree.get(key))

    def test_update_deserializer(self):
        exemplar = dict(status='enabled', foo='bar')
        intext = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                  '<updates><status>enabled</status><foo>bar</foo></updates>')
        result = self.deserializer.deserialize(intext)

        self.assertEqual(dict(body=exemplar), result)
