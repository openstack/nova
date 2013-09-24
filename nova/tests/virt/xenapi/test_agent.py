# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

import base64

from nova import test
from nova.virt.xenapi import agent


def _get_fake_instance(**kwargs):
    system_metadata = []
    for k, v in kwargs.items():
        system_metadata.append({
            "key": k,
            "value": v
        })

    return {
        "system_metadata": system_metadata,
        "uuid": "uuid",
        "key_data": "ssh-rsa asdf",
        "os_type": "asdf",
    }


class AgentTestCaseBase(test.NoDBTestCase):
    def _create_agent(self, instance):
        self.session = "session"
        self.virtapi = "virtapi"
        self.vm_ref = "vm_ref"
        return agent.XenAPIBasedAgent(self.session, self.virtapi,
                                      instance, self.vm_ref)


class AgentImageFlagsTestCase(AgentTestCaseBase):
    def test_agent_is_present(self):
        self.flags(xenapi_use_agent_default=False)
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "true"}]}
        self.assertTrue(agent.should_use_agent(instance))

    def test_agent_is_disabled(self):
        self.flags(xenapi_use_agent_default=True)
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "false"}]}
        self.assertFalse(agent.should_use_agent(instance))

    def test_agent_uses_deafault_when_prop_invalid(self):
        self.flags(xenapi_use_agent_default=True)
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "bob"}],
            "uuid": "uuid"}
        self.assertTrue(agent.should_use_agent(instance))

    def test_agent_default_not_present(self):
        self.flags(xenapi_use_agent_default=False)
        instance = {"system_metadata": []}
        self.assertFalse(agent.should_use_agent(instance))

    def test_agent_default_present(self):
        self.flags(xenapi_use_agent_default=True)
        instance = {"system_metadata": []}
        self.assertTrue(agent.should_use_agent(instance))


class SysMetaKeyTestBase():
    key = None

    def _create_agent_with_value(self, value):
        kwargs = {self.key: value}
        instance = _get_fake_instance(**kwargs)
        return self._create_agent(instance)

    def test_get_sys_meta_key_true(self):
        agent = self._create_agent_with_value("true")
        self.assertTrue(agent._get_sys_meta_key(self.key))

    def test_get_sys_meta_key_false(self):
        agent = self._create_agent_with_value("False")
        self.assertFalse(agent._get_sys_meta_key(self.key))

    def test_get_sys_meta_key_invalid_is_false(self):
        agent = self._create_agent_with_value("invalid")
        self.assertFalse(agent._get_sys_meta_key(self.key))

    def test_get_sys_meta_key_missing_is_false(self):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)
        self.assertFalse(agent._get_sys_meta_key(self.key))


class SkipSshFlagTestCase(SysMetaKeyTestBase, AgentTestCaseBase):
    key = "image_xenapi_skip_agent_inject_ssh"

    def test_skip_ssh_key_inject(self):
        agent = self._create_agent_with_value("True")
        self.assertTrue(agent._skip_ssh_key_inject())


class SkipFileInjectAtBootFlagTestCase(SysMetaKeyTestBase, AgentTestCaseBase):
    key = "image_xenapi_skip_agent_inject_files_at_boot"

    def test_skip_inject_files_at_boot(self):
        agent = self._create_agent_with_value("True")
        self.assertTrue(agent._skip_inject_files_at_boot())


class InjectSshTestCase(AgentTestCaseBase):
    def test_inject_ssh_key_succeeds(self):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)
        self.mox.StubOutWithMock(agent, "inject_file")

        agent.inject_file("/root/.ssh/authorized_keys",
            "\n# The following ssh key was injected by Nova"
            "\nssh-rsa asdf\n")

        self.mox.ReplayAll()
        agent.inject_ssh_key()

    def _test_inject_ssh_key_skipped(self, instance):
        agent = self._create_agent(instance)

        # make sure its not called
        self.mox.StubOutWithMock(agent, "inject_file")
        self.mox.ReplayAll()

        agent.inject_ssh_key()

    def test_inject_ssh_key_skipped_no_key_data(self):
        instance = _get_fake_instance()
        instance["key_data"] = None
        self._test_inject_ssh_key_skipped(instance)

    def test_inject_ssh_key_skipped_windows(self):
        instance = _get_fake_instance()
        instance["os_type"] = "windows"
        self._test_inject_ssh_key_skipped(instance)

    def test_inject_ssh_key_skipped_cloud_init_present(self):
        instance = _get_fake_instance(
                image_xenapi_skip_agent_inject_ssh="True")
        self._test_inject_ssh_key_skipped(instance)


class FileInjectionTestCase(AgentTestCaseBase):
    def test_inject_file(self):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)
        self.mox.StubOutWithMock(agent, "_call_agent")

        b64_path = base64.b64encode('path')
        b64_contents = base64.b64encode('contents')
        agent._call_agent('inject_file',
                          {'b64_contents': b64_contents,
                           'b64_path': b64_path})

        self.mox.ReplayAll()

        agent.inject_file("path", "contents")

    def test_inject_files(self):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)
        self.mox.StubOutWithMock(agent, "inject_file")

        files = [("path1", "content1"), ("path2", "content2")]
        agent.inject_file(*files[0])
        agent.inject_file(*files[1])

        self.mox.ReplayAll()

        agent.inject_files(files)

    def test_inject_files_skipped_when_cloud_init_installed(self):
        instance = _get_fake_instance(
                image_xenapi_skip_agent_inject_files_at_boot="True")
        agent = self._create_agent(instance)
        self.mox.StubOutWithMock(agent, "inject_file")

        files = [("path1", "content1"), ("path2", "content2")]

        self.mox.ReplayAll()

        agent.inject_files(files)
