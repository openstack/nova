# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Tests for the testing the metadata code."""

import base64
import webob

from nova.api.metadata import handler
from nova.db.sqlalchemy import api
from nova import db
from nova import exception
from nova import flags
from nova import network
from nova import test
from nova.tests import fake_network


FLAGS = flags.FLAGS

USER_DATA_STRING = ("This is an encoded string")
ENCODE_USER_DATA_STRING = base64.b64encode(USER_DATA_STRING)


def return_non_existing_server_by_address(context, address, *args, **kwarg):
    raise exception.NotFound()


class MetadataTestCase(test.TestCase):
    """Test that metadata is returning proper values."""

    def setUp(self):
        super(MetadataTestCase, self).setUp()
        self.instance = ({'id': 1,
                         'name': 'fake',
                         'project_id': 'test',
                         'key_name': None,
                         'host': 'test',
                         'launch_index': 1,
                         'instance_type': {'name': 'm1.tiny'},
                         'reservation_id': 'r-xxxxxxxx',
                         'user_data': '',
                         'image_ref': 7,
                         'vcpus': 1,
                         'fixed_ips': [],
                         'root_device_name': '/dev/sda1',
                         'hostname': 'test'})

        def fake_get_instance_nw_info(self, context, instance):
            return [(None, {'label': 'public',
                            'ips': [{'ip': '192.168.0.3'},
                                    {'ip': '192.168.0.4'}],
                            'ip6s': [{'ip': 'fe80::beef'}]})]

        def fake_get_floating_ips_by_fixed_address(self, context, fixed_ip):
            return ['1.2.3.4', '5.6.7.8']

        def instance_get(*args, **kwargs):
            return self.instance

        def instance_get_list(*args, **kwargs):
            return [self.instance]

        self.stubs.Set(network.API, 'get_instance_nw_info',
                fake_get_instance_nw_info)
        self.stubs.Set(network.API, 'get_floating_ips_by_fixed_address',
                fake_get_floating_ips_by_fixed_address)
        self.stubs.Set(api, 'instance_get', instance_get)
        self.stubs.Set(api, 'instance_get_all_by_filters', instance_get_list)
        self.app = handler.MetadataRequestHandler()
        network_manager = fake_network.FakeNetworkManager()
        self.stubs.Set(self.app.compute_api.network_api,
                       'get_instance_uuids_by_ip_filter',
                       network_manager.get_instance_uuids_by_ip_filter)

    def request(self, relative_url):
        request = webob.Request.blank(relative_url)
        request.remote_addr = "127.0.0.1"
        return request.get_response(self.app).body

    def test_base(self):
        self.assertEqual(self.request('/'), 'meta-data/\nuser-data')

    def test_user_data(self):
        self.instance['user_data'] = base64.b64encode('happy')
        self.assertEqual(self.request('/user-data'), 'happy')

    def test_security_groups(self):
        def sg_get(*args, **kwargs):
            return [{'name': 'default'}, {'name': 'other'}]
        self.stubs.Set(api, 'security_group_get_by_instance', sg_get)
        self.assertEqual(self.request('/meta-data/security-groups'),
                         'default\nother')

    def test_user_data_non_existing_fixed_address(self):
        self.stubs.Set(api, 'instance_get_all_by_filters',
                       return_non_existing_server_by_address)
        request = webob.Request.blank('/user-data')
        request.remote_addr = "127.1.1.1"
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 404)

    def test_user_data_none_fixed_address(self):
        self.stubs.Set(api, 'instance_get_all_by_filters',
                       return_non_existing_server_by_address)
        request = webob.Request.blank('/user-data')
        request.remote_addr = None
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 500)

    def test_user_data_invalid_url(self):
        request = webob.Request.blank('/user-data-invalid')
        request.remote_addr = "127.0.0.1"
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 404)

    def test_user_data_with_use_forwarded_header(self):
        self.instance['user_data'] = ENCODE_USER_DATA_STRING
        self.flags(use_forwarded_for=True)
        request = webob.Request.blank('/user-data')
        request.remote_addr = "127.0.0.1"
        response = request.get_response(self.app)
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.body, USER_DATA_STRING)

    def test_local_hostname_fqdn(self):
        self.assertEqual(self.request('/meta-data/local-hostname'),
            "%s.%s" % (self.instance['hostname'], FLAGS.dhcp_domain))

    def test_get_instance_mapping(self):
        """Make sure that _get_instance_mapping works"""
        ctxt = None
        instance_ref0 = {'id': 0,
                         'root_device_name': None}
        instance_ref1 = {'id': 0,
                         'root_device_name': '/dev/sda1'}

        def fake_bdm_get(ctxt, id):
            return [{'volume_id': 87654321,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': None,
                     'delete_on_termination': True,
                     'device_name': '/dev/sdh'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'swap',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdc'},
                    {'volume_id': None,
                     'snapshot_id': None,
                     'no_device': None,
                     'virtual_name': 'ephemeral0',
                     'delete_on_termination': None,
                     'device_name': '/dev/sdb'}]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdm_get)

        expected = {'ami': 'sda1',
                    'root': '/dev/sda1',
                    'ephemeral0': '/dev/sdb',
                    'swap': '/dev/sdc',
                    'ebs0': '/dev/sdh'}

        self.assertEqual(self.app._format_instance_mapping(ctxt,
                                                           instance_ref0),
                         handler._DEFAULT_MAPPINGS)
        self.assertEqual(self.app._format_instance_mapping(ctxt,
                                                           instance_ref1),
                         expected)
