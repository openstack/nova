# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from nova.tests.integrated.v3 import test_servers


class MultinicSampleJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-multinic"

    def _disable_instance_dns_manager(self):
        # NOTE(markmc): it looks like multinic and instance_dns_manager are
        #               incompatible. See:
        #               https://bugs.launchpad.net/nova/+bug/1213251
        self.flags(
            instance_dns_manager='nova.network.noop_dns_driver.NoopDNSDriver')

    def setUp(self):
        self._disable_instance_dns_manager()
        super(MultinicSampleJsonTest, self).setUp()
        self.uuid = self._post_server()

    def _add_fixed_ip(self):
        subs = {"networkId": 1}
        response = self._do_post('servers/%s/action' % (self.uuid),
                                 'multinic-add-fixed-ip-req', subs)
        self.assertEqual(response.status, 202)

    def test_add_fixed_ip(self):
        self._add_fixed_ip()

    def test_remove_fixed_ip(self):
        self._add_fixed_ip()

        subs = {"ip": "10.0.0.4"}
        response = self._do_post('servers/%s/action' % (self.uuid),
                                 'multinic-remove-fixed-ip-req', subs)
        self.assertEqual(response.status, 202)


class MultinicSampleXmlTest(MultinicSampleJsonTest):
    ctype = "xml"
