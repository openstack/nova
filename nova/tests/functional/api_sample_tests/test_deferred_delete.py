# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import test_servers

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class DeferredDeleteSampleJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-deferred-delete"

    def _get_flags(self):
        f = super(DeferredDeleteSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.deferred_delete.'
            'Deferred_delete')
        return f

    def setUp(self):
        super(DeferredDeleteSampleJsonTests, self).setUp()
        self.flags(reclaim_instance_interval=1)

    def test_restore(self):
        uuid = self._post_server()
        self._do_delete('servers/%s' % uuid)

        response = self._do_post('servers/%s/action' % uuid,
                                 'restore-post-req', {})
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.content)

    def test_force_delete(self):
        uuid = self._post_server()
        self._do_delete('servers/%s' % uuid)

        response = self._do_post('servers/%s/action' % uuid,
                                 'force-delete-post-req', {})
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.content)
