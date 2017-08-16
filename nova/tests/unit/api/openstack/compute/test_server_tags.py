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

import mock
from webob import exc

from nova.api.openstack.compute import server_tags
from nova.api.openstack.compute import servers
from nova.compute import vm_states
from nova import context
from nova.db.sqlalchemy import models
from nova import exception
from nova import objects
from nova.objects import instance
from nova.objects import tag as tag_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance

UUID = 'b48316c5-71e8-45e4-9884-6c78055b9b13'
TAG1 = 'tag1'
TAG2 = 'tag2'
TAG3 = 'tag3'
TAGS = [TAG1, TAG2, TAG3]
NON_EXISTING_UUID = '123'


def return_server(compute_api, context, instance_id, expected_attrs=None):
    return fake_instance.fake_instance_obj(context, vm_state=vm_states.ACTIVE)


def return_invalid_server(compute_api, context, instance_id,
                          expected_attrs=None):
    return fake_instance.fake_instance_obj(context,
                                           vm_state=vm_states.BUILDING)


class ServerTagsTest(test.TestCase):
    api_version = '2.26'

    def setUp(self):
        super(ServerTagsTest, self).setUp()
        self.controller = server_tags.ServerTagsController()
        inst_map = objects.InstanceMapping(
            cell_mapping=objects.CellMappingList.get_all(
                context.get_admin_context())[1])
        self.stub_out('nova.objects.InstanceMapping.get_by_instance_uuid',
                      lambda s, c, u: inst_map)

    def _get_tag(self, tag_name):
        tag = models.Tag()
        tag.tag = tag_name
        tag.resource_id = UUID
        return tag

    def _get_request(self, url, method):
        request = fakes.HTTPRequest.blank(url, version=self.api_version)
        request.method = method
        return request

    @mock.patch('nova.db.instance_tag_exists')
    def test_show(self, mock_exists):
        mock_exists.return_value = True
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG1), 'GET')

        self.controller.show(req, UUID, TAG1)
        mock_exists.assert_called_once_with(mock.ANY, UUID, TAG1)

    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    def test_index(self, mock_db_get_inst_tags):
        fake_tags = [self._get_tag(tag) for tag in TAGS]
        mock_db_get_inst_tags.return_value = fake_tags

        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'GET')

        res = self.controller.index(req, UUID)
        self.assertEqual(TAGS, res.get('tags'))
        mock_db_get_inst_tags.assert_called_once_with(mock.ANY, UUID)

    @mock.patch('nova.notifications.base.send_instance_update_notification')
    @mock.patch('nova.db.instance_tag_set')
    def test_update_all(self, mock_db_set_inst_tags, mock_notify):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        fake_tags = [self._get_tag(tag) for tag in TAGS]
        mock_db_set_inst_tags.return_value = fake_tags
        req = self._get_request(
            '/v2/fake/servers/%s/tags' % UUID, 'PUT')
        res = self.controller.update_all(req, UUID, body={'tags': TAGS})

        self.assertEqual(TAGS, res['tags'])
        mock_db_set_inst_tags.assert_called_once_with(mock.ANY, UUID, TAGS)
        self.assertEqual(1, mock_notify.call_count)

    def test_update_all_too_many_tags(self):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        fake_tags = {'tags': [str(i) for i in range(
            instance.MAX_TAG_COUNT + 1)]}

        req = self._get_request(
            '/v2/fake/servers/%s/tags' % UUID, 'PUT')
        self.assertRaises(exception.ValidationError,
                          self.controller.update_all,
                          req, UUID, body=fake_tags)

    def test_update_all_forbidden_characters(self):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'PUT')
        for tag in ['tag,1', 'tag/1']:
            self.assertRaises(exception.ValidationError,
                              self.controller.update_all,
                              req, UUID, body={'tags': [tag, 'tag2']})

    def test_update_all_invalid_tag_type(self):
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'PUT')
        self.assertRaises(exception.ValidationError,
                          self.controller.update_all,
                          req, UUID, body={'tags': [1]})

    def test_update_all_tags_with_one_tag_empty_string(self):
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'PUT')
        self.assertRaises(exception.ValidationError,
                          self.controller.update_all,
                          req, UUID, body={'tags': ['tag1', '']})

    def test_update_all_too_long_tag(self):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'PUT')
        tag = "a" * (tag_obj.MAX_TAG_LENGTH + 1)
        self.assertRaises(exception.ValidationError,
                          self.controller.update_all,
                          req, UUID, body={'tags': [tag]})

    def test_update_all_invalid_tag_list_type(self):
        req = self._get_request('/v2/ake/servers/%s/tags' % UUID, 'PUT')
        self.assertRaises(exception.ValidationError,
                          self.controller.update_all,
                          req, UUID, body={'tags': {'tag': 'tag'}})

    def test_update_all_invalid_instance_state(self):
        self.stub_out('nova.api.openstack.common.get_instance',
                      return_invalid_server)
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'PUT')
        self.assertRaises(exc.HTTPConflict, self.controller.update_all,
                          req, UUID, body={'tags': TAGS})

    @mock.patch('nova.db.instance_tag_exists')
    def test_show_non_existing_tag(self, mock_exists):
        mock_exists.return_value = False
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG1), 'GET')
        self.assertRaises(exc.HTTPNotFound, self.controller.show,
                          req, UUID, TAG1)

    @mock.patch('nova.notifications.base.send_instance_update_notification')
    @mock.patch('nova.db.instance_tag_add')
    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    def test_update(self, mock_db_get_inst_tags, mock_db_add_inst_tags,
                    mock_notify):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        mock_db_get_inst_tags.return_value = [self._get_tag(TAG1)]
        mock_db_add_inst_tags.return_value = self._get_tag(TAG2)

        url = '/v2/fake/servers/%s/tags/%s' % (UUID, TAG2)
        location = 'http://localhost' + url
        req = self._get_request(url, 'PUT')
        res = self.controller.update(req, UUID, TAG2, body=None)

        self.assertEqual(201, res.status_int)
        self.assertEqual(0, len(res.body))
        self.assertEqual(location, res.headers['Location'])
        mock_db_add_inst_tags.assert_called_once_with(mock.ANY, UUID, TAG2)
        self.assertEqual(2, mock_db_get_inst_tags.call_count)
        self.assertEqual(1, mock_notify.call_count)

    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    def test_update_existing_tag(self, mock_db_get_inst_tags):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        mock_db_get_inst_tags.return_value = [self._get_tag(TAG1)]

        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG1), 'PUT')
        res = self.controller.update(req, UUID, TAG1, body=None)

        self.assertEqual(204, res.status_int)
        self.assertEqual(0, len(res.body))
        mock_db_get_inst_tags.assert_called_once_with(mock.ANY, UUID)

    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    def test_update_tag_limit_exceed(self, mock_db_get_inst_tags):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        fake_tags = [self._get_tag(str(i))
                     for i in range(instance.MAX_TAG_COUNT)]
        mock_db_get_inst_tags.return_value = fake_tags

        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG2), 'PUT')
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, UUID, TAG2, body=None)

    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    def test_update_too_long_tag(self, mock_db_get_inst_tags):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        mock_db_get_inst_tags.return_value = []

        tag = "a" * (tag_obj.MAX_TAG_LENGTH + 1)
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, tag), 'PUT')
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, UUID, tag, body=None)

    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    def test_update_forbidden_characters(self, mock_db_get_inst_tags):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        mock_db_get_inst_tags.return_value = []
        for tag in ['tag,1', 'tag/1']:
            req = self._get_request(
                '/v2/fake/servers/%s/tags/%s' % (UUID, tag), 'PUT')
            self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                              req, UUID, tag, body=None)

    def test_update_invalid_instance_state(self):
        self.stub_out('nova.api.openstack.common.get_instance',
                      return_invalid_server)
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG1), 'PUT')
        self.assertRaises(exc.HTTPConflict, self.controller.update, req, UUID,
                          TAG1, body=None)

    @mock.patch('nova.db.instance_tag_get_by_instance_uuid')
    @mock.patch('nova.notifications.base.send_instance_update_notification')
    @mock.patch('nova.db.instance_tag_delete')
    def test_delete(self, mock_db_delete_inst_tags, mock_notify,
                    mock_db_get_inst_tags):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG2), 'DELETE')
        self.controller.delete(req, UUID, TAG2)
        mock_db_delete_inst_tags.assert_called_once_with(mock.ANY, UUID, TAG2)
        mock_db_get_inst_tags.assert_called_once_with(mock.ANY, UUID)
        self.assertEqual(1, mock_notify.call_count)

    @mock.patch('nova.db.instance_tag_delete')
    def test_delete_non_existing_tag(self, mock_db_delete_inst_tags):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)

        def fake_db_delete_tag(context, instance_uuid, tag):
            self.assertEqual(UUID, instance_uuid)
            self.assertEqual(TAG1, tag)
            raise exception.InstanceTagNotFound(instance_id=instance_uuid,
                                                tag=tag)
        mock_db_delete_inst_tags.side_effect = fake_db_delete_tag
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG1), 'DELETE')
        self.assertRaises(exc.HTTPNotFound, self.controller.delete,
                          req, UUID, TAG1)

    def test_delete_invalid_instance_state(self):
        self.stub_out('nova.api.openstack.common.get_instance',
                      return_invalid_server)
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (UUID, TAG2), 'DELETE')
        self.assertRaises(exc.HTTPConflict, self.controller.delete, req, UUID,
                          TAG1)

    @mock.patch('nova.notifications.base.send_instance_update_notification')
    @mock.patch('nova.db.instance_tag_delete_all')
    def test_delete_all(self, mock_db_delete_inst_tags, mock_notify):
        self.stub_out('nova.api.openstack.common.get_instance', return_server)
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'DELETE')
        self.controller.delete_all(req, UUID)
        mock_db_delete_inst_tags.assert_called_once_with(mock.ANY, UUID)
        self.assertEqual(1, mock_notify.call_count)

    def test_delete_all_invalid_instance_state(self):
        self.stub_out('nova.api.openstack.common.get_instance',
                      return_invalid_server)
        req = self._get_request('/v2/fake/servers/%s/tags' % UUID, 'DELETE')
        self.assertRaises(exc.HTTPConflict, self.controller.delete_all, req,
                          UUID)

    def test_show_non_existing_instance(self):
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (NON_EXISTING_UUID, TAG1), 'GET')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req,
                          NON_EXISTING_UUID, TAG1)

    def test_show_with_details_information_non_existing_instance(self):
        req = self._get_request(
            '/v2/fake/servers/%s' % NON_EXISTING_UUID, 'GET')
        servers_controller = servers.ServersController()
        self.assertRaises(exc.HTTPNotFound, servers_controller.show, req,
                          NON_EXISTING_UUID)

    def test_index_non_existing_instance(self):
        req = self._get_request(
            'v2/fake/servers/%s/tags' % NON_EXISTING_UUID, 'GET')
        self.assertRaises(exc.HTTPNotFound, self.controller.index, req,
                          NON_EXISTING_UUID)

    def test_update_non_existing_instance(self):
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (NON_EXISTING_UUID, TAG1), 'PUT')
        self.assertRaises(exc.HTTPNotFound, self.controller.update, req,
                          NON_EXISTING_UUID, TAG1, body=None)

    def test_update_all_non_existing_instance(self):
        req = self._get_request(
            '/v2/fake/servers/%s/tags' % NON_EXISTING_UUID, 'PUT')
        self.assertRaises(exc.HTTPNotFound, self.controller.update_all, req,
                          NON_EXISTING_UUID, body={'tags': TAGS})

    def test_delete_non_existing_instance(self):
        req = self._get_request(
            '/v2/fake/servers/%s/tags/%s' % (NON_EXISTING_UUID, TAG1),
            'DELETE')
        self.assertRaises(exc.HTTPNotFound, self.controller.delete, req,
                          NON_EXISTING_UUID, TAG1)

    def test_delete_all_non_existing_instance(self):
            req = self._get_request(
                '/v2/fake/servers/%s/tags' % NON_EXISTING_UUID, 'DELETE')
            self.assertRaises(exc.HTTPNotFound, self.controller.delete_all,
                              req, NON_EXISTING_UUID)
