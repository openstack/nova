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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import six

from nova.objects import resource
from nova.tests.unit.objects import test_objects


fake_resources = resource.ResourceList(objects=[
    resource.Resource(provider_uuid=uuids.rp, resource_class='CUSTOM_RESOURCE',
                      identifier='foo'),
    resource.Resource(provider_uuid=uuids.rp, resource_class='CUSTOM_RESOURCE',
                      identifier='bar')])

fake_vpmems = [
    resource.LibvirtVPMEMDevice(
            label='4GB', name='ns_0', devpath='/dev/dax0.0',
            size=4292870144, align=2097152),
    resource.LibvirtVPMEMDevice(
            label='4GB', name='ns_1', devpath='/dev/dax0.0',
            size=4292870144, align=2097152)]

fake_instance_extras = {
    'resources': jsonutils.dumps(fake_resources.obj_to_primitive())
}


class TestResourceObject(test_objects._LocalTest):
    def _create_resource(self, metadata=None):
        fake_resource = resource.Resource(provider_uuid=uuids.rp,
                                          resource_class='bar',
                                          identifier='foo')
        if metadata:
            fake_resource.metadata = metadata
        return fake_resource

    def _test_set_malformed_resource_class(self, rc):
        try:
            resource.Resource(provider_uuid=uuids.rp,
                              resource_class=rc,
                              identifier='foo')
        except ValueError as e:
            self.assertEqual('Malformed Resource Class %s' % rc,
                             six.text_type(e))
        else:
            self.fail('Check malformed resource class failed.')

    def _test_set_formed_resource_class(self, rc):
        resource.Resource(provider_uuid=uuids.rp,
                          resource_class=rc,
                          identifier='foo')

    def test_set_malformed_resource_classes(self):
        malformed_resource_classes = ['!', ';', ' ']
        for rc in malformed_resource_classes:
            self._test_set_malformed_resource_class(rc)

    def test_set_formed_resource_classes(self):
        formed_resource_classes = ['resource', 'RESOURCE', '0123']
        for rc in formed_resource_classes:
            self._test_set_formed_resource_class(rc)

    def test_equal_without_metadata(self):
        resource_0 = resource.Resource(provider_uuid=uuids.rp,
                                       resource_class='bar',
                                       identifier='foo')
        resource_1 = resource.Resource(provider_uuid=uuids.rp,
                                       resource_class='bar',
                                       identifier='foo')
        self.assertEqual(resource_0, resource_1)

    def test_not_equal_without_matadata(self):
        self.assertNotEqual(fake_resources[0], fake_resources[1])

    def test_equal_with_vpmem_metadata(self):
        resource_0 = self._create_resource(metadata=fake_vpmems[0])
        resource_1 = self._create_resource(metadata=fake_vpmems[0])
        self.assertEqual(resource_0, resource_1)

    def test_not_equal_with_vpmem_metadata(self):
        resource_0 = self._create_resource(metadata=fake_vpmems[0])
        resource_1 = self._create_resource(metadata=fake_vpmems[1])
        self.assertNotEqual(resource_0, resource_1)

    def test_not_equal_with_and_without_metadata(self):
        # one resource has metadata, another one has not metadata
        resource_0 = self._create_resource(metadata=fake_vpmems[0])
        resource_1 = self._create_resource()
        self.assertNotEqual(resource_0, resource_1)


class _TestResourceListObject(object):
    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = fake_instance_extras
        resources = resource.ResourceList.get_by_instance_uuid(
            self.context, 'fake_uuid')
        for i in range(len(resources)):
            self.assertEqual(resources[i].identifier,
                             fake_resources[i].identifier)


class TestResourceListObject(test_objects._LocalTest,
                             _TestResourceListObject):
    pass


class TestRemoteResourceListObject(test_objects._RemoteTest,
                                   _TestResourceListObject):
    pass
