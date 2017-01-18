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

import mock
from oslo_utils import timeutils
from webob import exc

from nova.api.openstack.compute import cloudpipe as cloudpipe_v21
from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network
from nova.tests.unit import matchers
from nova.tests import uuidsentinel as uuids
from nova import utils

CONF = nova.conf.CONF


project_id = str(uuid_lib.uuid4().hex)
uuid = uuids.fake


def fake_vpn_instance():
    return objects.Instance(
        id=7, image_ref=CONF.cloudpipe.vpn_image_id, vm_state='active',
        created_at=timeutils.parse_strtime('1981-10-20T00:00:00.000000'),
        uuid=uuid, project_id=project_id)


def compute_api_get_all(context, search_opts=None):
        return [fake_vpn_instance()]


class CloudpipeTestV21(test.NoDBTestCase):
    cloudpipe = cloudpipe_v21
    url = '/v2/fake/os-cloudpipe'

    def setUp(self):
        super(CloudpipeTestV21, self).setUp()
        self.controller = self.cloudpipe.CloudpipeController()
        self.req = fakes.HTTPRequest.blank('')

    def test_cloudpipe_list_no_network(self):
        with test.nested(
            mock.patch.object(compute_utils, 'get_nw_info_for_instance',
                              return_value={}),
            mock.patch.object(self.controller.compute_api, "get_all",
                              side_effect=compute_api_get_all)
        ) as (mock_utils_get_nw, mock_cpu_get_all):
            res_dict = self.controller.index(self.req)
            response = {'cloudpipes': [{'project_id': project_id,
                                        'instance_id': uuid,
                                        'created_at': '1981-10-20T00:00:00Z'}]}

            self.assertEqual(response, res_dict)
            self.assertTrue(mock_cpu_get_all.called)
            self.assertTrue(mock_utils_get_nw.called)

    def test_cloudpipe_list(self):

        def network_api_get(context, network_id):
            self.assertEqual(context.project_id, project_id)
            return {'vpn_public_address': '127.0.0.1',
                    'vpn_public_port': 22}

        def fake_get_nw_info_for_instance(instance):
            return fake_network.fake_get_instance_nw_info(self)

        with test.nested(
            mock.patch.object(utils, 'vpn_ping', return_value=True),
            mock.patch.object(compute_utils, 'get_nw_info_for_instance',
                              side_effect=fake_get_nw_info_for_instance),
            mock.patch.object(self.controller.network_api, "get",
                              side_effect=network_api_get),
            mock.patch.object(self.controller.compute_api, "get_all",
                              side_effect=compute_api_get_all)
        ) as (mock_vpn_ping, mock_utils_get, mock_nw_get, mock_cpu_get_all):
            res_dict = self.controller.index(self.req)
            response = {'cloudpipes': [{'project_id': project_id,
                                        'internal_ip': '192.168.1.100',
                                        'public_ip': '127.0.0.1',
                                        'public_port': 22,
                                        'state': 'running',
                                        'instance_id': uuid,
                                        'created_at': '1981-10-20T00:00:00Z'}]}

            self.assertThat(response, matchers.DictMatches(res_dict))
            self.assertTrue(mock_cpu_get_all.called)
            self.assertTrue(mock_nw_get.called)
            self.assertTrue(mock_utils_get.called)
            self.assertTrue(mock_vpn_ping.called)

    def test_cloudpipe_create(self):
        def _launch_vpn_instance(context):
            return ([fake_vpn_instance()], 'fake-reservation')

        with test.nested(
            mock.patch.object(self.controller.compute_api, "get_all",
                              return_value=[]),
            mock.patch.object(self.controller.cloudpipe,
                              'launch_vpn_instance',
                              side_effect=_launch_vpn_instance),
        ) as (mock_cpu_get_all, mock_vpn_launch):
            body = {'cloudpipe': {'project_id': project_id}}
            res_dict = self.controller.create(self.req, body=body)
            response = {'instance_id': uuid}

            self.assertEqual(response, res_dict)
            self.assertTrue(mock_cpu_get_all.called)
            self.assertTrue(mock_vpn_launch.called)

    def test_cloudpipe_create_no_networks(self):
        with test.nested(
            mock.patch.object(self.controller.compute_api, "get_all",
                              return_value=[]),
            mock.patch.object(self.controller.cloudpipe,
                              'launch_vpn_instance',
                              side_effect=exception.NoMoreNetworks),
        ) as (mock_cpu_get_all, mock_vpn_launch):
            body = {'cloudpipe': {'project_id': project_id}}
            req = fakes.HTTPRequest.blank(self.url)

            self.assertRaises(exc.HTTPBadRequest,
                              self.controller.create, req, body=body)
            self.assertTrue(mock_cpu_get_all.called)
            self.assertTrue(mock_vpn_launch.called)

    def test_cloudpipe_create_already_running(self):
        with test.nested(
            mock.patch.object(self.controller.cloudpipe,
                              'launch_vpn_instance'),
            mock.patch.object(self.controller.compute_api, "get_all",
                              side_effect=compute_api_get_all),
        ) as (mock_vpn_launch, mock_cpu_get_all):
            body = {'cloudpipe': {'project_id': project_id}}
            req = fakes.HTTPRequest.blank(self.url)
            res_dict = self.controller.create(req, body=body)
            response = {'instance_id': uuid}

            self.assertEqual(response, res_dict)
            # cloudpipe.launch_vpn_instance() should not be called
            self.assertFalse(mock_vpn_launch.called)
            self.assertTrue(mock_cpu_get_all.called)

    def test_cloudpipe_create_with_bad_project_id_failed(self):
        body = {'cloudpipe': {'project_id': 'bad.project.id'}}
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)


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
