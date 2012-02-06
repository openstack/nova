# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
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

import string

from nova import test
from nova.volume import iscsi


class TargetAdminTestCase(object):

    def setUp(self):
        self.cmds = []

        self.tid = 1
        self.target_name = 'iqn.2011-09.org.foo.bar:blaa'
        self.lun = 10
        self.path = '/foo/bar/blaa'

        self.script_template = None

    def get_script_params(self):
        return {'tid': self.tid,
                'target_name': self.target_name,
                'lun': self.lun,
                'path': self.path}

    def get_script(self):
        return self.script_template % self.get_script_params()

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def clear_cmds(self):
        cmds = []

    def verify_cmds(self, cmds):
        self.assertEqual(len(cmds), len(self.cmds))
        for a, b in zip(cmds, self.cmds):
            self.assertEqual(a, b)

    def verify(self):
        script = self.get_script()
        cmds = []
        for line in script.split('\n'):
            if not line.strip():
                continue
            cmds.append(line)
        self.verify_cmds(cmds)

    def run_commands(self):
        tgtadm = iscsi.get_target_admin()
        tgtadm.set_execute(self.fake_execute)
        tgtadm.new_target(self.target_name, self.tid)
        tgtadm.show_target(self.tid)
        tgtadm.new_logicalunit(self.tid, self.lun, self.path)
        tgtadm.delete_logicalunit(self.tid, self.lun)
        tgtadm.delete_target(self.tid)

    def test_target_admin(self):
        self.clear_cmds()
        self.run_commands()
        self.verify()


class TgtAdmTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(TgtAdmTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='tgtadm')
        self.script_template = "\n".join([
        "tgtadm --op new --lld=iscsi --mode=target --tid=%(tid)s "
                "--targetname=%(target_name)s",
        "tgtadm --op bind --lld=iscsi --mode=target --initiator-address=ALL "
                "--tid=%(tid)s",
        "tgtadm --op show --lld=iscsi --mode=target --tid=%(tid)s",
        "tgtadm --op new --lld=iscsi --mode=logicalunit --tid=%(tid)s "
                "--lun=%(lun)d --backing-store=%(path)s",
        "tgtadm --op delete --lld=iscsi --mode=logicalunit --tid=%(tid)s "
                "--lun=%(lun)d",
        "tgtadm --op delete --lld=iscsi --mode=target --tid=%(tid)s"])

    def get_script_params(self):
        params = super(TgtAdmTestCase, self).get_script_params()
        params['lun'] += 1
        return params


class IetAdmTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(IetAdmTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='ietadm')
        self.script_template = "\n".join([
        "ietadm --op new --tid=%(tid)s --params Name=%(target_name)s",
        "ietadm --op show --tid=%(tid)s",
        "ietadm --op new --tid=%(tid)s --lun=%(lun)d "
                "--params Path=%(path)s,Type=fileio",
        "ietadm --op delete --tid=%(tid)s --lun=%(lun)d",
        "ietadm --op delete --tid=%(tid)s"])
