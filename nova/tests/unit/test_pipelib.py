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

from oslo_config import cfg

from nova.cloudpipe import pipelib
from nova import context
from nova import crypto
from nova import test
from nova import utils

CONF = cfg.CONF


class PipelibTest(test.TestCase):
    def setUp(self):
        super(PipelibTest, self).setUp()
        self.cloudpipe = pipelib.CloudPipe()
        self.project = "222"
        self.user = "111"
        self.context = context.RequestContext(self.user, self.project)

    def test_get_encoded_zip(self):
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir)
            crypto.ensure_ca_filesystem()

            ret = self.cloudpipe.get_encoded_zip(self.project)
            self.assertTrue(ret)

    def test_launch_vpn_instance(self):
        self.stubs.Set(self.cloudpipe.compute_api,
                       "create",
                       lambda *a, **kw: (None, "r-fakeres"))
        with utils.tempdir() as tmpdir:
            self.flags(ca_path=tmpdir, keys_path=tmpdir)
            crypto.ensure_ca_filesystem()
            self.cloudpipe.launch_vpn_instance(self.context)

    def test_setup_security_group(self):
        group_name = "%s%s" % (self.project, CONF.vpn_key_suffix)

        # First attempt, does not exist (thus its created)
        res1_group = self.cloudpipe.setup_security_group(self.context)
        self.assertEqual(res1_group, group_name)

        # Second attempt, it exists in the DB
        res2_group = self.cloudpipe.setup_security_group(self.context)
        self.assertEqual(res1_group, res2_group)

    def test_setup_key_pair(self):
        key_name = "%s%s" % (self.project, CONF.vpn_key_suffix)
        with utils.tempdir() as tmpdir:
            self.flags(keys_path=tmpdir)

            # First attempt, key does not exist (thus it is generated)
            res1_key = self.cloudpipe.setup_key_pair(self.context)
            self.assertEqual(res1_key, key_name)

            # Second attempt, it exists in the DB
            res2_key = self.cloudpipe.setup_key_pair(self.context)
            self.assertEqual(res2_key, res1_key)
