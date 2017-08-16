# Copyright 2013 IBM Corp.
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

import webob

from nova.api.openstack.compute import block_device_mapping \
        as block_device_mapping_v21
from nova.api.openstack.compute import multiple_create as multiple_create_v21
from nova.api.openstack.compute import servers as servers_v21
from nova.compute import api as compute_api
import nova.conf
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake

CONF = nova.conf.CONF


def return_security_group(context, instance_id, security_group_id):
    pass


class MultiCreateExtensionTestV21(test.TestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(MultiCreateExtensionTestV21, self).setUp()

        self.flags(enable_instance_password=True, group='api')
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        # Network API needs to be stubbed out before creating the controllers.
        fakes.stub_out_nw_api(self)

        self.controller = servers_v21.ServersController()

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def server_update(context, instance_uuid, params,
                          columns_to_join=None):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            self.instance_cache_by_uuid[instance.uuid] = instance
            return instance

        fakes.stub_out_key_pair_funcs(self)
        fake.stub_out_image_service(self)
        self.stub_out('nova.db.instance_add_security_group',
                      return_security_group)
        self.stub_out('nova.db.project_get_networks', project_get_networks)
        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)
        self.stub_out('nova.db.instance_system_metadata_update', fake_method)
        self.stub_out('nova.db.instance_get', instance_get)
        self.stub_out('nova.db.instance_update', instance_update)
        self.stub_out('nova.db.instance_update_and_get_original',
                      server_update)
        self.stub_out('nova.network.manager.VlanManager.allocate_fixed_ip',
                      fake_method)
        self.req = fakes.HTTPRequest.blank('')

    def _test_create_extra(self, params, no_image=False):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        if no_image:
            server.pop('imageRef', None)
        server.update(params)
        body = dict(server=server)
        server = self.controller.create(self.req,
                                        body=body).obj['server']

    def test_multiple_create_with_string_type_min_and_max(self):
        min_count = '2'
        max_count = '3'
        params = {
            multiple_create_v21.MIN_ATTRIBUTE_NAME: min_count,
            multiple_create_v21.MAX_ATTRIBUTE_NAME: max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsInstance(kwargs['min_count'], int)
            self.assertIsInstance(kwargs['max_count'], int)
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_extra(params)

    def test_create_instance_with_multiple_create_enabled(self):
        min_count = 2
        max_count = 3
        params = {
            multiple_create_v21.MIN_ATTRIBUTE_NAME: min_count,
            multiple_create_v21.MAX_ATTRIBUTE_NAME: max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_extra(params)

    def test_create_instance_invalid_negative_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: -1,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(self.validation_error,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_negative_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MAX_ATTRIBUTE_NAME: -1,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(self.validation_error,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_with_blank_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: '',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(self.validation_error,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_with_blank_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MAX_ATTRIBUTE_NAME: '',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(self.validation_error,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_min_greater_than_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 4,
                multiple_create_v21.MAX_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_alpha_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 'abcd',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(self.validation_error,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_alpha_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create_v21.MAX_ATTRIBUTE_NAME: 'abcd',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(self.validation_error,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_multiple_instances(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        res = self.controller.create(self.req, body=body).obj

        instance_uuids = self.instance_cache_by_uuid.keys()
        self.assertIn(res["server"]["id"], instance_uuids)
        self._check_admin_password_len(res["server"])

    def test_create_multiple_instances_pass_disabled(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        self.flags(enable_instance_password=False, group='api')
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        res = self.controller.create(self.req, body=body).obj

        instance_uuids = self.instance_cache_by_uuid.keys()
        self.assertIn(res["server"]["id"], instance_uuids)
        self._check_admin_password_missing(res["server"])

    def _check_admin_password_len(self, server_dict):
        """utility function - check server_dict for admin_password length."""
        self.assertEqual(CONF.password_length,
                         len(server_dict["adminPass"]))

    def _check_admin_password_missing(self, server_dict):
        """utility function - check server_dict for admin_password absence."""
        self.assertNotIn("admin_password", server_dict)

    def _create_multiple_instances_resv_id_return(self, resv_id_return):
        """Test creating multiple instances with asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
                multiple_create_v21.RRID_ATTRIBUTE_NAME: resv_id_return
            }
        }

        res = self.controller.create(self.req, body=body)
        reservation_id = res.obj['reservation_id']
        self.assertNotEqual(reservation_id, "")
        self.assertIsNotNone(reservation_id)
        self.assertGreater(len(reservation_id), 1)

    def test_create_multiple_instances_with_resv_id_return(self):
        self._create_multiple_instances_resv_id_return(True)

    def test_create_multiple_instances_with_string_resv_id_return(self):
        self._create_multiple_instances_resv_id_return("True")

    def test_create_multiple_instances_with_multiple_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested with a list of block device mappings for volumes.
        """
        min_count = 2
        bdm = [{'source_type': 'volume', 'uuid': 'vol-xxxx'},
               {'source_type': 'volume', 'uuid': 'vol-yyyy'}
        ]
        params = {
                  block_device_mapping_v21.ATTRIBUTE_NAME: bdm,
                  multiple_create_v21.MIN_ATTRIBUTE_NAME: min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(len(kwargs['block_device_mapping']), 2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        exc = self.assertRaises(webob.exc.HTTPBadRequest,
                                self._test_create_extra, params, no_image=True)
        self.assertEqual("Cannot attach one or more volumes to multiple "
                         "instances", exc.explanation)

    def test_create_multiple_instances_with_single_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested to boot from a single volume.
        """
        min_count = 2
        bdm = [{'source_type': 'volume', 'uuid': 'vol-xxxx'}]
        params = {
                 block_device_mapping_v21.ATTRIBUTE_NAME: bdm,
                 multiple_create_v21.MIN_ATTRIBUTE_NAME: min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['block_device_mapping'][0]['volume_id'],
                            'vol-xxxx')
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        exc = self.assertRaises(webob.exc.HTTPBadRequest,
                                self._test_create_extra, params, no_image=True)
        self.assertEqual("Cannot attach one or more volumes to multiple "
                         "instances", exc.explanation)

    def test_create_multiple_instance_with_non_integer_max_count(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MAX_ATTRIBUTE_NAME: 2.5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_create_multiple_instance_with_non_integer_min_count(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 2.5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_create_multiple_instance_max_count_overquota_min_count_ok(self):
        self.flags(instances=3, group='quota')
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 2,
                multiple_create_v21.MAX_ATTRIBUTE_NAME: 5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        res = self.controller.create(self.req, body=body).obj
        instance_uuids = self.instance_cache_by_uuid.keys()
        self.assertIn(res["server"]["id"], instance_uuids)

    def test_create_multiple_instance_max_count_overquota_min_count_over(self):
        self.flags(instances=3, group='quota')
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create_v21.MIN_ATTRIBUTE_NAME: 4,
                multiple_create_v21.MAX_ATTRIBUTE_NAME: 5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          self.req, body=body)
