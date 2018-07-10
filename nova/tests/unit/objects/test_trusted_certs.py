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

from nova.objects import trusted_certs
from nova.tests.unit.objects import test_objects
from oslo_serialization import jsonutils

fake_trusted_certs = trusted_certs.TrustedCerts(ids=['fake-trusted-cert-1',
                                                     'fake-trusted-cert-2'])
fake_instance_extras = {
    'trusted_certs': jsonutils.dumps(fake_trusted_certs.obj_to_primitive())
}


class _TestTrustedCertsObject(object):

    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = fake_instance_extras
        certs = trusted_certs.TrustedCerts.get_by_instance_uuid(
            self.context, 'fake_uuid')
        self.assertEqual(certs.ids, fake_trusted_certs.ids)


class TestTrustedCertsObject(test_objects._LocalTest,
                             _TestTrustedCertsObject):
    pass


class TestRemoteTrustedCertsObject(test_objects._RemoteTest,
                                    _TestTrustedCertsObject):
    pass
