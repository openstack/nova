# Copyright (c) 2011 OpenStack Foundation
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
import testtools
import webob.exc

from nova.api.openstack.compute.plugins.v3 import hosts as os_hosts
from nova.compute import power_state
from nova.compute import vm_states
from nova import context as context_maker
from nova import db
from nova import exception
from nova import test
from nova.tests import fake_hosts


def stub_service_get_all(context, disabled=None):
    return fake_hosts.SERVICES_LIST


def stub_service_get_by_host_and_topic(context, host_name, topic):
    for service in stub_service_get_all(context):
        if service['host'] == host_name and service['topic'] == topic:
            return service


def stub_set_host_enabled(context, host_name, enabled):
    """
    Simulates three possible behaviours for VM drivers or compute drivers when
    enabling or disabling a host.

    'enabled' means new instances can go to this host
    'disabled' means they can't
    """
    results = {True: "enabled", False: "disabled"}
    if host_name == "notimplemented":
        # The vm driver for this host doesn't support this feature
        raise NotImplementedError()
    elif host_name == "dummydest":
        # The host does not exist
        raise exception.ComputeHostNotFound(host=host_name)
    elif host_name == "host_c2":
        # Simulate a failure
        return results[not enabled]
    elif host_name == "serviceunavailable":
        raise exception.ComputeServiceUnavailable(host=host_name)
    else:
        # Do the right thing
        return results[enabled]


def stub_set_host_maintenance(context, host_name, mode):
    # We'll simulate success and failure by assuming
    # that 'host_c1' always succeeds, and 'host_c2'
    # always fails
    results = {True: "on_maintenance", False: "off_maintenance"}
    if host_name == "notimplemented":
        # The vm driver for this host doesn't support this feature
        raise NotImplementedError()
    elif host_name == "dummydest":
        # The host does not exist
        raise exception.ComputeHostNotFound(host=host_name)
    elif host_name == "host_c2":
        # Simulate a failure
        return results[not mode]
    elif host_name == "serviceunavailable":
        raise exception.ComputeServiceUnavailable(host=host_name)
    else:
        # Do the right thing
        return results[mode]


def stub_host_power_action(context, host_name, action):
    if host_name == "notimplemented":
        raise NotImplementedError()
    elif host_name == "dummydest":
        # The host does not exist
        raise exception.ComputeHostNotFound(host=host_name)
    elif host_name == "serviceunavailable":
        raise exception.ComputeServiceUnavailable(host=host_name)
    return action


def _create_instance(**kwargs):
    """Create a test instance."""
    ctxt = context_maker.get_admin_context()
    return db.instance_create(ctxt, _create_instance_dict(**kwargs))


def _create_instance_dict(**kwargs):
    """Create a dictionary for a test instance."""
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
    environ = {"nova.context": context_maker.get_admin_context()}
    GET = {}


class FakeRequestWithNovaZone(object):
    environ = {"nova.context": context_maker.get_admin_context()}
    GET = {"zone": "nova"}


class HostTestCase(test.TestCase):
    """Test Case for hosts."""

    def setUp(self):
        super(HostTestCase, self).setUp()
        self.controller = os_hosts.HostController()
        self.hosts_api = self.controller.api
        self.req = FakeRequest()

        # Pretend we have fake_hosts.HOST_LIST in the DB
        self.stubs.Set(db, 'service_get_all',
                       stub_service_get_all)
        # Only hosts in our fake DB exist
        self.stubs.Set(db, 'service_get_by_host_and_topic',
                       stub_service_get_by_host_and_topic)
        # 'host_c1' always succeeds, and 'host_c2'
        self.stubs.Set(self.hosts_api, 'set_host_enabled',
                       stub_set_host_enabled)
        # 'host_c1' always succeeds, and 'host_c2'
        self.stubs.Set(self.hosts_api, 'set_host_maintenance',
                       stub_set_host_maintenance)
        self.stubs.Set(self.hosts_api, 'host_power_action',
                       stub_host_power_action)

    def _test_host_update(self, host, key, val, expected_value):
        body = {'host': {key: val}}
        result = self.controller.update(self.req, host, body)
        self.assertEqual(result['host'][key], expected_value)

    def test_list_hosts(self):
        """Verify that the compute hosts are returned."""
        result = self.controller.index(self.req)
        self.assertIn('hosts', result)
        hosts = result['hosts']
        self.assertEqual(fake_hosts.HOST_LIST, hosts)

    def test_list_hosts_with_zone(self):
        result = self.controller.index(FakeRequestWithNovaZone())
        self.assertIn('hosts', result)
        hosts = result['hosts']
        self.assertEqual(fake_hosts.HOST_LIST_NOVA_ZONE, hosts)

    def test_disable_host(self):
        self._test_host_update('host_c1', 'status', 'disable', 'disabled')
        self._test_host_update('host_c2', 'status', 'disable', 'enabled')

    def test_enable_host(self):
        self._test_host_update('host_c1', 'status', 'enable', 'enabled')
        self._test_host_update('host_c2', 'status', 'enable', 'disabled')

    def test_enable_maintenance(self):
        self._test_host_update('host_c1', 'maintenance_mode',
                               'enable', 'on_maintenance')

    def test_disable_maintenance(self):
        self._test_host_update('host_c1', 'maintenance_mode',
                               'disable', 'off_maintenance')

    def _test_host_update_service_unavailable(self, key, val):
        body = {'host': {key: val}}
        host = "serviceunavailable"
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, host, body)

    def test_enable_host_service_unavailable(self):
        self._test_host_update_service_unavailable('status', 'enable')

    def test_enable_maintenance_service_unavaliable(self):
        self._test_host_update_service_unavailable('maintenance_mode',
                                                   'enable')

    def _test_host_update_notimpl(self, key, val):
        def stub_service_get_all_notimpl(self, req):
            return [{'host': 'notimplemented', 'topic': None,
                     'availability_zone': None}]
        self.stubs.Set(db, 'service_get_all',
                       stub_service_get_all_notimpl)
        body = {"host": {key: val}}
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.controller.update,
                          self.req, 'notimplemented', body=body)

    def test_disable_host_notimpl(self):
        self._test_host_update_notimpl('status', 'disable')

    def test_enable_maintenance_notimpl(self):
        self._test_host_update_notimpl('maintenance_mode', 'enable')

    def test_host_startup(self):
        result = self.controller.startup(self.req, "host_c1")
        self.assertEqual(result['host']["power_action"], "startup")

    def test_host_shutdown(self):
        result = self.controller.shutdown(self.req, "host_c1")
        self.assertEqual(result['host']["power_action"], "shutdown")

    def test_host_reboot(self):
        result = self.controller.reboot(self.req, "host_c1")
        self.assertEqual(result['host']["power_action"], "reboot")

    def _test_host_power_action_service_unavailable(self, method):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          method, self.req, "serviceunavailable")

    def test_host_startup_service_unavailable(self):
        self._test_host_power_action_service_unavailable(
            self.controller.startup)

    def test_host_shutdown_service_unavailable(self):
        self._test_host_power_action_service_unavailable(
            self.controller.shutdown)

    def test_host_reboot_service_unavailable(self):
        self._test_host_power_action_service_unavailable(
            self.controller.reboot)

    def _test_host_power_action_notimpl(self, method):
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          method, self.req, "notimplemented")

    def test_host_startup_notimpl(self):
        self._test_host_power_action_notimpl(self.controller.startup)

    def test_host_shutdown_notimpl(self):
        self._test_host_power_action_notimpl(self.controller.shutdown)

    def test_host_reboot_notimpl(self):
        self._test_host_power_action_notimpl(self.controller.reboot)

    def test_host_status_bad_host(self):
        # A host given as an argument does not exist.
        self.req.environ["nova.context"].is_admin = True
        dest = 'dummydest'
        with testtools.ExpectedException(webob.exc.HTTPNotFound,
                                         ".*%s.*" % dest):
            self.controller.update(self.req, dest,
                                   body={"host": {'status': 'enable'}})

    def test_host_maintenance_bad_host(self):
        # A host given as an argument does not exist.
        self.req.environ["nova.context"].is_admin = True
        dest = 'dummydest'
        with testtools.ExpectedException(webob.exc.HTTPNotFound,
                                         ".*%s.*" % dest):
            self.controller.update(self.req, dest,
                                   body={"host": {
                                         'maintenance_mode': 'enable'}})

    def test_host_power_action_bad_host(self):
        # A host given as an argument does not exist.
        self.req.environ["nova.context"].is_admin = True
        dest = 'dummydest'
        with testtools.ExpectedException(webob.exc.HTTPNotFound,
                                         ".*%s.*" % dest):
            self.controller.reboot(self.req, dest)

    def test_bad_status_value(self):
        bad_body = {"host": {"status": "bad"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body)
        bad_body2 = {"host": {"status": "disablabc"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body2)

    def test_bad_update_key(self):
        bad_body = {"host": {"crazy": "bad"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body)

    def test_bad_update_key_type(self):
        bad_body = {"host": "abc"}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body)
        bad_body = {"host": None}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body)

    def test_bad_update_empty(self):
        bad_body = {}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body)

    def test_bad_update_key_and_correct_update_key(self):
        bad_body = {"host": {"status": "disable",
                             "crazy": "bad"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, "host_c1", bad_body)

    def test_good_update_keys(self):
        body = {"host": {"status": "disable",
                         "maintenance_mode": "enable"}}
        result = self.controller.update(self.req, 'host_c1', body)
        self.assertEqual(result["host"]["host"], "host_c1")
        self.assertEqual(result["host"]["status"], "disabled")
        self.assertEqual(result["host"]["maintenance_mode"],
                         "on_maintenance")

    def test_show_forbidden(self):
        self.req.environ["nova.context"].is_admin = False
        dest = 'dummydest'
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show,
                          self.req, dest)
        self.req.environ["nova.context"].is_admin = True

    def test_show_host_not_exist(self):
        # A host given as an argument does not exist.
        self.req.environ["nova.context"].is_admin = True
        dest = 'dummydest'
        with testtools.ExpectedException(webob.exc.HTTPNotFound,
                                         ".*%s.*" % dest):
            self.controller.show(self.req, dest)

    def _create_compute_service(self):
        """Create compute-manager(ComputeNode and Service record)."""
        ctxt = self.req.environ["nova.context"]
        dic = {'host': 'dummy', 'binary': 'nova-compute', 'topic': 'compute',
               'report_count': 0}
        s_ref = db.service_create(ctxt, dic)

        dic = {'service_id': s_ref['id'],
               'vcpus': 16, 'memory_mb': 32, 'local_gb': 100,
               'vcpus_used': 16, 'memory_mb_used': 32, 'local_gb_used': 10,
               'hypervisor_type': 'qemu', 'hypervisor_version': 12003,
               'cpu_info': '', 'stats': {}}
        db.compute_node_create(ctxt, dic)

        return db.service_get(ctxt, s_ref['id'])

    def test_show_no_project(self):
        """No instances are running on the given host."""
        ctxt = context_maker.get_admin_context()
        s_ref = self._create_compute_service()

        result = self.controller.show(self.req, s_ref['host'])

        proj = ['(total)', '(used_now)', '(used_max)']
        column = ['host', 'project', 'cpu', 'memory_mb', 'disk_gb']
        self.assertEqual(len(result['host']), 3)
        for resource in result['host']:
            self.assertIn(resource['resource']['project'], proj)
            self.assertEqual(len(resource['resource']), 5)
            self.assertTrue(set(resource['resource'].keys()) == set(column))
        db.service_destroy(ctxt, s_ref['id'])

    def test_show_works_correctly(self):
        """show() works correctly as expected."""
        ctxt = context_maker.get_admin_context()
        s_ref = self._create_compute_service()
        i_ref1 = _create_instance(project_id='p-01', host=s_ref['host'])
        i_ref2 = _create_instance(project_id='p-02', vcpus=3,
                                  host=s_ref['host'])

        result = self.controller.show(self.req, s_ref['host'])

        proj = ['(total)', '(used_now)', '(used_max)', 'p-01', 'p-02']
        column = ['host', 'project', 'cpu', 'memory_mb', 'disk_gb']
        self.assertEqual(len(result['host']), 5)
        for resource in result['host']:
            self.assertIn(resource['resource']['project'], proj)
            self.assertEqual(len(resource['resource']), 5)
            self.assertTrue(set(resource['resource'].keys()) == set(column))
        db.service_destroy(ctxt, s_ref['id'])
        db.instance_destroy(ctxt, i_ref1['uuid'])
        db.instance_destroy(ctxt, i_ref2['uuid'])


class HostSerializerTest(test.TestCase):
    def setUp(self):
        super(HostSerializerTest, self).setUp()

    def test_index_serializer(self):
        serializer = os_hosts.HostIndexTemplate()
        text = serializer.serialize(fake_hosts.OS_API_HOST_LIST)

        tree = etree.fromstring(text)

        self.assertEqual('hosts', tree.tag)
        self.assertEqual(len(fake_hosts.HOST_LIST), len(tree))
        for i in range(len(fake_hosts.HOST_LIST)):
            self.assertEqual('host', tree[i].tag)
            self.assertEqual(fake_hosts.HOST_LIST[i]['host_name'],
                             tree[i].get('host_name'))
            self.assertEqual(fake_hosts.HOST_LIST[i]['service'],
                             tree[i].get('service'))
            self.assertEqual(fake_hosts.HOST_LIST[i]['zone'],
                             tree[i].get('zone'))
