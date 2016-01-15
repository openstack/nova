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

import uuid as uuid_lib

from oslo_config import cfg
from oslo_utils import timeutils
from webob import exc

from nova.api.openstack.compute import cloudpipe as cloudpipe_v21
from nova.api.openstack.compute.legacy_v2.contrib import cloudpipe \
        as cloudpipe_v2
from nova.compute import utils as compute_utils
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network
from nova.tests.unit import matchers
from nova import utils

CONF = cfg.CONF
CONF.import_opt('vpn_image_id', 'nova.cloudpipe.pipelib')


project_id = str(uuid_lib.uuid4().hex)
uuid = str(uuid_lib.uuid4())


def fake_vpn_instance():
    return objects.Instance(
        id=7, image_ref=CONF.vpn_image_id, vm_state='active',
        created_at=timeutils.parse_strtime('1981-10-20T00:00:00.000000'),
        uuid=uuid, project_id=project_id)


def compute_api_get_all_empty(context, search_opts=None, want_objects=True):
    return []


def compute_api_get_all(context, search_opts=None, want_objects=True):
        return [fake_vpn_instance()]


def utils_vpn_ping(addr, port, timoeout=0.05, session_id=None):
    return True


class CloudpipeTestV21(test.NoDBTestCase):
    cloudpipe = cloudpipe_v21
    url = '/v2/fake/os-cloudpipe'

    def setUp(self):
        super(CloudpipeTestV21, self).setUp()
        self.controller = self.cloudpipe.CloudpipeController()
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all_empty)
        self.stubs.Set(utils, 'vpn_ping', utils_vpn_ping)
        self.req = fakes.HTTPRequest.blank('')

    def test_cloudpipe_list_no_network(self):

        def fake_get_nw_info_for_instance(instance):
            return {}

        self.stubs.Set(compute_utils, "get_nw_info_for_instance",
                       fake_get_nw_info_for_instance)
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all)
        res_dict = self.controller.index(self.req)
        response = {'cloudpipes': [{'project_id': project_id,
                                    'instance_id': uuid,
                                    'created_at': '1981-10-20T00:00:00Z'}]}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_list(self):

        def network_api_get(context, network_id):
            self.assertEqual(context.project_id, project_id)
            return {'vpn_public_address': '127.0.0.1',
                    'vpn_public_port': 22}

        def fake_get_nw_info_for_instance(instance):
            return fake_network.fake_get_instance_nw_info(self)

        self.stubs.Set(compute_utils, "get_nw_info_for_instance",
                       fake_get_nw_info_for_instance)
        self.stubs.Set(self.controller.network_api, "get",
                       network_api_get)
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all)
        res_dict = self.controller.index(self.req)
        response = {'cloudpipes': [{'project_id': project_id,
                                    'internal_ip': '192.168.1.100',
                                    'public_ip': '127.0.0.1',
                                    'public_port': 22,
                                    'state': 'running',
                                    'instance_id': uuid,
                                    'created_at': '1981-10-20T00:00:00Z'}]}
        self.assertThat(res_dict, matchers.DictMatches(response))

    def test_cloudpipe_create(self):
        def launch_vpn_instance(context):
            return ([fake_vpn_instance()], 'fake-reservation')

        self.stubs.Set(self.controller.cloudpipe, 'launch_vpn_instance',
                       launch_vpn_instance)
        body = {'cloudpipe': {'project_id': project_id}}
        res_dict = self.controller.create(self.req, body=body)

        response = {'instance_id': uuid}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_create_no_networks(self):
        def launch_vpn_instance(context):
            raise exception.NoMoreNetworks

        self.stubs.Set(self.controller.cloudpipe, 'launch_vpn_instance',
                       launch_vpn_instance)
        body = {'cloudpipe': {'project_id': project_id}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create, req, body=body)

    def test_cloudpipe_create_already_running(self):
        def launch_vpn_instance(*args, **kwargs):
            self.fail("Method should not have been called")

        self.stubs.Set(self.controller.cloudpipe, 'launch_vpn_instance',
                       launch_vpn_instance)
        self.stubs.Set(self.controller.compute_api, "get_all",
                       compute_api_get_all)
        body = {'cloudpipe': {'project_id': project_id}}
        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.create(req, body=body)
        response = {'instance_id': uuid}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_create_with_bad_project_id_failed(self):
        body = {'cloudpipe': {'project_id': 'bad.project.id'}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)


class CloudpipeTestV2(CloudpipeTestV21):
    cloudpipe = cloudpipe_v2

    def test_cloudpipe_create_with_bad_project_id_failed(self):
        pass


class CloudpipePolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(CloudpipePolicyEnforcementV21, self).setUp()
        self.controller = cloudpipe_v21.CloudpipeController()
        self.req = fakes.HTTPRequest.blank('')

    def _common_policy_check(self, func, *arg, **kwarg):
        rule_name = "os_compute_api:os-cloudpipe"
        rule = {rule_name: "project:non_fake"}
        self.policy.set_rules(rule)
        exc = self.assertRaises(
            exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_list_policy_failed(self):
        self._common_policy_check(self.controller.index, self.req)

    def test_create_policy_failed(self):
        body = {'cloudpipe': {'project_id': uuid}}
        self._common_policy_check(self.controller.create, self.req, body=body)

    def test_update_policy_failed(self):
        body = {"configure_project": {'vpn_ip': '192.168.1.1',
                                      'vpn_port': 2000}}
        self._common_policy_check(
            self.controller.update, self.req, uuid, body=body)
