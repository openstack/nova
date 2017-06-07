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
import time

import mock
from os_xenapi.client import host_agent
from os_xenapi.client import XenAPI
from oslo_utils import uuidutils

from nova import exception
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
    def _create_agent(self, instance, session="session"):
        self.session = session
        self.virtapi = "virtapi"
        self.vm_ref = "vm_ref"
        return agent.XenAPIBasedAgent(self.session, self.virtapi,
                                      instance, self.vm_ref)


class AgentImageFlagsTestCase(AgentTestCaseBase):
    def test_agent_is_present(self):
        self.flags(use_agent_default=False, group='xenserver')
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "true"}]}
        self.assertTrue(agent.should_use_agent(instance))

    def test_agent_is_disabled(self):
        self.flags(use_agent_default=True, group='xenserver')
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "false"}]}
        self.assertFalse(agent.should_use_agent(instance))

    def test_agent_uses_deafault_when_prop_invalid(self):
        self.flags(use_agent_default=True, group='xenserver')
        instance = {"system_metadata":
            [{"key": "image_xenapi_use_agent", "value": "bob"}],
            "uuid": "uuid"}
        self.assertTrue(agent.should_use_agent(instance))

    def test_agent_default_not_present(self):
        self.flags(use_agent_default=False, group='xenserver')
        instance = {"system_metadata": []}
        self.assertFalse(agent.should_use_agent(instance))

    def test_agent_default_present(self):
        self.flags(use_agent_default=True, group='xenserver')
        instance = {"system_metadata": []}
        self.assertTrue(agent.should_use_agent(instance))


class SysMetaKeyTestBase(object):
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
    @mock.patch.object(agent.XenAPIBasedAgent, 'inject_file')
    def test_inject_ssh_key_succeeds(self, mock_inject_file):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)

        agent.inject_ssh_key()
        mock_inject_file.assert_called_once_with("/root/.ssh/authorized_keys",
                                                 "\n# The following ssh key "
                                                 "was injected by Nova"
                                                 "\nssh-rsa asdf\n")

    @mock.patch.object(agent.XenAPIBasedAgent, 'inject_file')
    def _test_inject_ssh_key_skipped(self, instance, mock_inject_file):
        agent = self._create_agent(instance)

        # make sure its not called
        agent.inject_ssh_key()
        mock_inject_file.assert_not_called()

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
    @mock.patch.object(agent.XenAPIBasedAgent, '_call_agent')
    def test_inject_file(self, mock_call_agent):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)

        b64_path = base64.b64encode(b'path')
        b64_contents = base64.b64encode(b'contents')

        agent.inject_file("path", "contents")
        mock_call_agent.assert_called_once_with(host_agent.inject_file,
                                                {'b64_contents': b64_contents,
                                                 'b64_path': b64_path})

    @mock.patch.object(agent.XenAPIBasedAgent, 'inject_file')
    def test_inject_files(self, mock_inject_file):
        instance = _get_fake_instance()
        agent = self._create_agent(instance)

        files = [("path1", "content1"), ("path2", "content2")]

        agent.inject_files(files)
        mock_inject_file.assert_has_calls(
            [mock.call("path1", "content1"), mock.call("path2", "content2")])

    @mock.patch.object(agent.XenAPIBasedAgent, 'inject_file')
    def test_inject_files_skipped_when_cloud_init_installed(self,
                                                            mock_inject_file):
        instance = _get_fake_instance(
                image_xenapi_skip_agent_inject_files_at_boot="True")
        agent = self._create_agent(instance)

        files = [("path1", "content1"), ("path2", "content2")]

        agent.inject_files(files)
        mock_inject_file.assert_not_called()


class RebootRetryTestCase(AgentTestCaseBase):
    @mock.patch.object(agent, '_wait_for_new_dom_id')
    def test_retry_on_reboot(self, mock_wait):
        mock_session = mock.Mock()
        mock_session.VM.get_domid.return_value = "fake_dom_id"
        agent = self._create_agent(None, mock_session)
        mock_method = mock.Mock().method()
        mock_method.side_effect = [XenAPI.Failure(["REBOOT: fake"]),
                                   {"returncode": '0', "message": "done"}]
        result = agent._call_agent(mock_method)
        self.assertEqual("done", result)
        self.assertTrue(mock_session.VM.get_domid.called)
        self.assertEqual(2, mock_method.call_count)
        mock_wait.assert_called_once_with(mock_session, self.vm_ref,
                                          "fake_dom_id", mock_method)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(time, 'time')
    def test_wait_for_new_dom_id_found(self, mock_time, mock_sleep):
        mock_session = mock.Mock()
        mock_session.VM.get_domid.return_value = "new"

        agent._wait_for_new_dom_id(mock_session, "vm_ref", "old", "method")

        mock_session.VM.get_domid.assert_called_once_with("vm_ref")
        self.assertFalse(mock_sleep.called)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(time, 'time')
    def test_wait_for_new_dom_id_after_retry(self, mock_time, mock_sleep):
        self.flags(agent_timeout=3, group="xenserver")
        mock_time.return_value = 0
        mock_session = mock.Mock()
        old = "40"
        new = "42"
        mock_session.VM.get_domid.side_effect = [old, "-1", new]

        agent._wait_for_new_dom_id(mock_session, "vm_ref", old, "method")

        mock_session.VM.get_domid.assert_called_with("vm_ref")
        self.assertEqual(3, mock_session.VM.get_domid.call_count)
        self.assertEqual(2, mock_sleep.call_count)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(time, 'time')
    def test_wait_for_new_dom_id_timeout(self, mock_time, mock_sleep):
        self.flags(agent_timeout=3, group="xenserver")

        def fake_time():
            fake_time.time = fake_time.time + 1
            return fake_time.time

        fake_time.time = 0
        mock_time.side_effect = fake_time
        mock_session = mock.Mock()
        mock_session.VM.get_domid.return_value = "old"
        mock_method = mock.Mock().method()
        mock_method.__name__ = "mock_method"

        self.assertRaises(exception.AgentTimeout,
                          agent._wait_for_new_dom_id,
                          mock_session, "vm_ref", "old", mock_method)

        self.assertEqual(4, mock_session.VM.get_domid.call_count)


class SetAdminPasswordTestCase(AgentTestCaseBase):
    @mock.patch.object(agent.XenAPIBasedAgent, '_call_agent')
    @mock.patch("nova.virt.xenapi.agent.SimpleDH")
    def test_exchange_key_with_agent(self, mock_simple_dh, mock_call_agent):
        agent = self._create_agent(None)
        instance_mock = mock_simple_dh()
        instance_mock.get_public.return_value = 4321
        mock_call_agent.return_value = "1234"

        result = agent._exchange_key_with_agent()

        mock_call_agent.assert_called_once_with(host_agent.key_init,
                                                {"pub": "4321"},
                                                success_codes=['D0'],
                                                ignore_errors=False)
        result.compute_shared.assert_called_once_with(1234)

    @mock.patch.object(agent.XenAPIBasedAgent, '_call_agent')
    @mock.patch.object(agent.XenAPIBasedAgent,
                       '_save_instance_password_if_sshkey_present')
    @mock.patch.object(agent.XenAPIBasedAgent, '_exchange_key_with_agent')
    def test_set_admin_password_works(self, mock_exchange, mock_save,
                                      mock_call_agent):
        mock_dh = mock.Mock(spec_set=agent.SimpleDH)
        mock_dh.encrypt.return_value = "enc_pass"
        mock_exchange.return_value = mock_dh
        agent_inst = self._create_agent(None)

        agent_inst.set_admin_password("new_pass")

        mock_dh.encrypt.assert_called_once_with("new_pass\n")
        mock_call_agent.assert_called_once_with(host_agent.password,
                                                {'enc_pass': 'enc_pass'})
        mock_save.assert_called_once_with("new_pass")

    @mock.patch.object(agent.XenAPIBasedAgent, '_add_instance_fault')
    @mock.patch.object(agent.XenAPIBasedAgent, '_exchange_key_with_agent')
    def test_set_admin_password_silently_fails(self, mock_exchange,
                                               mock_add_fault):
        error = exception.AgentTimeout(method="fake")
        mock_exchange.side_effect = error
        agent_inst = self._create_agent(None)

        agent_inst.set_admin_password("new_pass")

        mock_add_fault.assert_called_once_with(error, mock.ANY)


class UpgradeRequiredTestCase(test.NoDBTestCase):
    def test_less_than(self):
        self.assertTrue(agent.is_upgrade_required('1.2.3.4', '1.2.3.5'))

    def test_greater_than(self):
        self.assertFalse(agent.is_upgrade_required('1.2.3.5', '1.2.3.4'))

    def test_equal(self):
        self.assertFalse(agent.is_upgrade_required('1.2.3.4', '1.2.3.4'))

    def test_non_lexical(self):
        self.assertFalse(agent.is_upgrade_required('1.2.3.10', '1.2.3.4'))

    def test_length(self):
        self.assertTrue(agent.is_upgrade_required('1.2.3', '1.2.3.4'))


@mock.patch.object(uuidutils, 'generate_uuid')
class CallAgentTestCase(AgentTestCaseBase):
    def test_call_agent_success(self, mock_uuid):
        session = mock.Mock()
        instance = {"uuid": "fake"}
        addl_args = {"foo": "bar"}

        session.VM.get_domid.return_value = '42'
        mock_uuid.return_value = 1
        mock_method = mock.Mock().method()
        mock_method.return_value = {'returncode': '4', 'message': "asdf\\r\\n"}
        mock_method.__name__ = "mock_method"

        self.assertEqual("asdf",
                         agent._call_agent(session, instance, "vm_ref",
                                           mock_method, addl_args, timeout=300,
                                           success_codes=['0', '4']))

        expected_args = {}
        expected_args.update(addl_args)
        mock_method.assert_called_once_with(session, 1, '42', 300,
                                            **expected_args)
        session.VM.get_domid.assert_called_once_with("vm_ref")

    def _call_agent_setup(self, session, mock_uuid, mock_method,
                          returncode='0', success_codes=None,
                          exception=None):
        session.XenAPI.Failure = XenAPI.Failure
        instance = {"uuid": "fake"}
        addl_args = {"foo": "bar"}

        session.VM.get_domid.return_value = "42"
        mock_uuid.return_value = 1
        if exception:
            mock_method.side_effect = exception
        else:
            mock_method.return_value = {'returncode': returncode,
                                        'message': "asdf\\r\\n"}

        return agent._call_agent(session, instance, "vm_ref", mock_method,
                                 addl_args, success_codes=success_codes)

    def _assert_agent_called(self, session, mock_uuid, mock_method):
        expected_args = {"foo": "bar"}
        mock_uuid.assert_called_once_with()
        mock_method.assert_called_once_with(session, 1, '42', 30,
                                            **expected_args)
        session.VM.get_domid.assert_called_once_with("vm_ref")

    def test_call_agent_works_with_defaults(self, mock_uuid):
        session = mock.Mock()
        mock_method = mock.Mock().method()
        mock_method.__name__ = "mock_method"
        self._call_agent_setup(session, mock_uuid, mock_method)
        self._assert_agent_called(session, mock_uuid, mock_method)

    def test_call_agent_fails_with_timeout(self, mock_uuid):
        session = mock.Mock()
        mock_method = mock.Mock().method()
        mock_method.__name__ = "mock_method"
        self.assertRaises(exception.AgentTimeout, self._call_agent_setup,
                          session, mock_uuid, mock_method,
                          exception=XenAPI.Failure(["TIMEOUT:fake"]))
        self._assert_agent_called(session, mock_uuid, mock_method)

    def test_call_agent_fails_with_not_implemented(self, mock_uuid):
        session = mock.Mock()
        mock_method = mock.Mock().method()
        mock_method.__name__ = "mock_method"
        self.assertRaises(exception.AgentNotImplemented,
                          self._call_agent_setup,
                          session, mock_uuid, mock_method,
                          exception=XenAPI.Failure(["NOT IMPLEMENTED:"]))
        self._assert_agent_called(session, mock_uuid, mock_method)

    def test_call_agent_fails_with_other_error(self, mock_uuid):
        session = mock.Mock()
        mock_method = mock.Mock().method()
        mock_method.__name__ = "mock_method"
        self.assertRaises(exception.AgentError, self._call_agent_setup,
                          session, mock_uuid, mock_method,
                          exception=XenAPI.Failure(["asdf"]))
        self._assert_agent_called(session, mock_uuid, mock_method)

    def test_call_agent_fails_with_returned_error(self, mock_uuid):
        session = mock.Mock()
        mock_method = mock.Mock().method()
        mock_method.__name__ = "mock_method"
        self.assertRaises(exception.AgentError, self._call_agent_setup,
                          session, mock_uuid, mock_method, returncode='42')
        self._assert_agent_called(session, mock_uuid, mock_method)


class XenAPIBasedAgent(AgentTestCaseBase):
    @mock.patch.object(agent.XenAPIBasedAgent, "_add_instance_fault")
    @mock.patch.object(agent, "_call_agent")
    def test_call_agent_swallows_error(self, mock_call_agent,
                                       mock_add_instance_fault):
        fake_error = exception.AgentError(method="bob")
        mock_call_agent.side_effect = fake_error

        instance = _get_fake_instance()
        agent = self._create_agent(instance)

        agent._call_agent("bob")

        mock_call_agent.assert_called_once_with(agent.session, agent.instance,
                agent.vm_ref, "bob", None, None, None)
        mock_add_instance_fault.assert_called_once_with(fake_error, mock.ANY)

    @mock.patch.object(agent.XenAPIBasedAgent, "_add_instance_fault")
    @mock.patch.object(agent, "_call_agent")
    def test_call_agent_throws_error(self, mock_call_agent,
                                     mock_add_instance_fault):
        fake_error = exception.AgentError(method="bob")
        mock_call_agent.side_effect = fake_error

        instance = _get_fake_instance()
        agent = self._create_agent(instance)

        self.assertRaises(exception.AgentError, agent._call_agent,
                          "bob", ignore_errors=False)

        mock_call_agent.assert_called_once_with(agent.session, agent.instance,
                agent.vm_ref, "bob", None, None, None)
        self.assertFalse(mock_add_instance_fault.called)
