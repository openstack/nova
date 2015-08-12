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

from nova.tests.functional.v3 import test_servers

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.extensions')


class ServersIpsJsonTest(test_servers.ServersSampleBase):
    extends_name = 'core_only'
    sample_dir = 'server-ips'
    extra_extensions_to_load = ["os-access-ips"]
    # TODO(park): Overriding '_api_version' till all functional tests
    # are merged between v2 and v2.1. After that base class variable
    # itself can be changed to 'v2'
    _api_version = 'v2'

    def test_get(self):
        # Test getting a server's IP information.
        uuid = self._post_server()
        response = self._do_get('servers/%s/ips' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-ips-resp', subs, response, 200)

    def test_get_by_network(self):
        # Test getting a server's IP information by network id.
        uuid = self._post_server()
        response = self._do_get('servers/%s/ips/private' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-ips-network-resp', subs, response, 200)
