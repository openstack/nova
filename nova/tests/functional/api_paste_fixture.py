# Copyright 2015 NEC Corporation.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

import fixtures
from oslo_config import cfg

from nova import paths


CONF = cfg.CONF


class ApiPasteV21Fixture(fixtures.Fixture):

    def _replace_line(self, target_file, line):
        # TODO(johnthetubaguy) should really point the tests at /v2.1
        target_file.write(line.replace(
            "/v2: openstack_compute_api_v21_legacy_v2_compatible",
            "/v2: openstack_compute_api_v21"))

    def setUp(self):
        super(ApiPasteV21Fixture, self).setUp()
        CONF.set_default('api_paste_config',
                         paths.state_path_def('etc/nova/api-paste.ini'),
                         group='wsgi')
        tmp_api_paste_dir = self.useFixture(fixtures.TempDir())
        tmp_api_paste_file_name = os.path.join(tmp_api_paste_dir.path,
                                               'fake_api_paste.ini')
        with open(CONF.wsgi.api_paste_config, 'r') as orig_api_paste:
            with open(tmp_api_paste_file_name, 'w') as tmp_file:
                for line in orig_api_paste:
                    self._replace_line(tmp_file, line)
        CONF.set_override('api_paste_config', tmp_api_paste_file_name,
                          group='wsgi')


class ApiPasteLegacyV2Fixture(ApiPasteV21Fixture):

    def _replace_line(self, target_file, line):
        # NOTE(johnthetubaguy) this is hack so we test the legacy_v2 code
        # even though its disable by default in api-paste.ini
        line = line.replace(
            "/v2: openstack_compute_api_v21_legacy_v2_compatible",
            "/v2: openstack_compute_api_legacy_v2")
        target_file.write(line)


class ApiPasteNoProjectId(ApiPasteV21Fixture):

    def _replace_line(self, target_file, line):
        line = line.replace(
            "paste.filter_factory = nova.api.openstack.auth:"
            "NoAuthMiddleware.factory",
            "paste.filter_factory = nova.api.openstack.auth:"
            "NoAuthMiddlewareV2_18.factory")
        target_file.write(line)
