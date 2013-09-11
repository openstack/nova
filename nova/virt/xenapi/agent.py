# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010-2012 OpenStack Foundation
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
import binascii
import os
import time
import uuid

from oslo.config import cfg

from nova.api.metadata import password
from nova import context
from nova import crypto
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova import utils


USE_AGENT_KEY = "xenapi_use_agent"
USE_AGENT_SM_KEY = utils.SM_IMAGE_PROP_PREFIX + USE_AGENT_KEY
SKIP_SSH_KEY = "xenapi_skip_agent_inject_ssh"
SKIP_SSH_SM_KEY = utils.SM_IMAGE_PROP_PREFIX + SKIP_SSH_KEY
SKIP_FILES_AT_BOOT_KEY = "xenapi_skip_agent_inject_files_at_boot"
SKIP_FILES_AT_BOOT_SM_KEY = utils.SM_IMAGE_PROP_PREFIX \
                                        + SKIP_FILES_AT_BOOT_KEY

LOG = logging.getLogger(__name__)

xenapi_agent_opts = [
    cfg.IntOpt('agent_timeout',
               default=30,
               help='number of seconds to wait for agent reply'),
    cfg.IntOpt('agent_version_timeout',
               default=300,
               help='number of seconds to wait for agent '
                    'to be fully operational'),
    cfg.IntOpt('agent_resetnetwork_timeout',
               default=60,
               help='number of seconds to wait for agent reply '
                    'to resetnetwork request'),
    cfg.StrOpt('xenapi_agent_path',
               default='usr/sbin/xe-update-networking',
               help='Specifies the path in which the xenapi guest agent '
                    'should be located. If the agent is present, network '
                    'configuration is not injected into the image. '
                    'Used if compute_driver=xenapi.XenAPIDriver and '
                    ' flat_injected=True'),
    cfg.BoolOpt('xenapi_disable_agent',
               default=False,
               help='Disables the use of the XenAPI agent in any image '
                    'regardless of what image properties are present. '),
    cfg.BoolOpt('xenapi_use_agent_default',
               default=False,
               help='Determines if the xenapi agent should be used when '
                    'the image used does not contain a hint to declare if '
                    'the agent is present or not. '
                    'The hint is a glance property "' + USE_AGENT_KEY + '" '
                    'that has the value "true" or "false". '
                    'Note that waiting for the agent when it is not present '
                    'will significantly increase server boot times.'),
]

CONF = cfg.CONF
CONF.register_opts(xenapi_agent_opts)


def _call_agent(session, instance, vm_ref, method, addl_args=None,
                timeout=None, success_codes=None):
    """Abstracts out the interaction with the agent xenapi plugin."""
    if addl_args is None:
        addl_args = {}
    if timeout is None:
        timeout = CONF.agent_timeout
    if success_codes is None:
        success_codes = ['0']

    vm_rec = session.call_xenapi("VM.get_record", vm_ref)

    args = {
        'id': str(uuid.uuid4()),
        'dom_id': vm_rec['domid'],
        'timeout': str(timeout),
    }
    args.update(addl_args)

    try:
        ret = session.call_plugin('agent', method, args)
    except session.XenAPI.Failure as e:
        err_msg = e.details[-1].splitlines()[-1]
        if 'TIMEOUT:' in err_msg:
            LOG.error(_('TIMEOUT: The call to %(method)s timed out. '
                        'args=%(args)r'),
                      {'method': method, 'args': args}, instance=instance)
            raise exception.AgentTimeout(method=method)
        elif 'NOT IMPLEMENTED:' in err_msg:
            LOG.error(_('NOT IMPLEMENTED: The call to %(method)s is not '
                        'supported by the agent. args=%(args)r'),
                      {'method': method, 'args': args}, instance=instance)
            raise exception.AgentNotImplemented(method=method)
        else:
            LOG.error(_('The call to %(method)s returned an error: %(e)s. '
                        'args=%(args)r'),
                      {'method': method, 'args': args, 'e': e},
                      instance=instance)
            raise exception.AgentError(method=method)

    if not isinstance(ret, dict):
        try:
            ret = jsonutils.loads(ret)
        except TypeError:
            LOG.error(_('The agent call to %(method)s returned an invalid '
                        'response: %(ret)r. args=%(args)r'),
                      {'method': method, 'ret': ret, 'args': args},
                      instance=instance)
            raise exception.AgentError(method=method)

    if ret['returncode'] not in success_codes:
        LOG.error(_('The agent call to %(method)s returned an '
                    'an error: %(ret)r. args=%(args)r'),
                  {'method': method, 'ret': ret, 'args': args},
                  instance=instance)
        raise exception.AgentError(method=method)

    LOG.debug(_('The agent call to %(method)s was successful: '
                '%(ret)r. args=%(args)r'),
              {'method': method, 'ret': ret, 'args': args},
              instance=instance)

    # Some old versions of the Windows agent have a trailing \\r\\n
    # (ie CRLF escaped) for some reason. Strip that off.
    return ret['message'].replace('\\r\\n', '')


class XenAPIBasedAgent(object):
    def __init__(self, session, virtapi, instance, vm_ref):
        self.session = session
        self.virtapi = virtapi
        self.instance = instance
        self.vm_ref = vm_ref

    def _call_agent(self, method, addl_args=None, timeout=None,
                    success_codes=None):
        return _call_agent(self.session, self.instance, self.vm_ref,
                           method, addl_args, timeout, success_codes)

    def get_agent_version(self):
        """Get the version of the agent running on the VM instance."""

        LOG.debug(_('Querying agent version'), instance=self.instance)

        # The agent can be slow to start for a variety of reasons. On Windows,
        # it will generally perform a setup process on first boot that can
        # take a couple of minutes and then reboot. On Linux, the system can
        # also take a while to boot. So we need to be more patient than
        # normal as well as watch for domid changes

        expiration = time.time() + CONF.agent_version_timeout
        while True:
            try:
                return self._call_agent('version')
            except exception.AgentTimeout:
                if time.time() > expiration:
                    raise

    def agent_update(self, agent_build):
        """Update agent on the VM instance."""

        LOG.debug(_('Updating agent to %s'), agent_build['version'],
                  instance=self.instance)

        # Send the encrypted password
        args = {'url': agent_build['url'], 'md5sum': agent_build['md5hash']}
        try:
            self._call_agent('agentupdate', args)
        except exception.AgentError as exc:
            # Silently fail for agent upgrades
            LOG.warning(_("Unable to update the agent due "
                          "to: %(exc)s") % dict(exc=exc),
                        instance=self.instance)

    def _exchange_key_with_agent(self):
        dh = SimpleDH()
        args = {'pub': str(dh.get_public())}
        resp = self._call_agent('key_init', args, success_codes=['D0'])
        agent_pub = int(resp)
        dh.compute_shared(agent_pub)
        return dh

    def _save_instance_password_if_sshkey_present(self, new_pass):
        sshkey = self.instance.get('key_data')
        if sshkey and sshkey.startswith("ssh-rsa"):
            ctxt = context.get_admin_context()
            enc = crypto.ssh_encrypt_text(sshkey, new_pass)
            sys_meta = utils.instance_sys_meta(self.instance)
            sys_meta.update(password.convert_password(ctxt,
                                                      base64.b64encode(enc)))
            self.virtapi.instance_update(ctxt, self.instance['uuid'],
                                         {'system_metadata': sys_meta})

    def set_admin_password(self, new_pass):
        """Set the root/admin password on the VM instance.

        This is done via an agent running on the VM. Communication between nova
        and the agent is done via writing xenstore records. Since communication
        is done over the XenAPI RPC calls, we need to encrypt the password.
        We're using a simple Diffie-Hellman class instead of a more advanced
        library (such as M2Crypto) for compatibility with the agent code.
        """
        LOG.debug(_('Setting admin password'), instance=self.instance)

        dh = self._exchange_key_with_agent()
        # Some old versions of Linux and Windows agent expect trailing \n
        # on password to work correctly.
        enc_pass = dh.encrypt(new_pass + '\n')

        args = {'enc_pass': enc_pass}
        self._call_agent('password', args)
        self._save_instance_password_if_sshkey_present(new_pass)

    def inject_ssh_key(self):
        sshkey = self.instance.get('key_data')
        if not sshkey:
            return

        if self.instance['os_type'] == 'windows':
            LOG.debug(_("Skipping setting of ssh key for Windows."),
                      instance=self.instance)
            return

        if self._skip_ssh_key_inject():
            LOG.debug(_("Skipping agent ssh key injection for this image."),
                      instance=self.instance)
            return

        sshkey = str(sshkey)
        keyfile = '/root/.ssh/authorized_keys'
        key_data = ''.join([
            '\n',
            '# The following ssh key was injected by Nova',
            '\n',
            sshkey.strip(),
            '\n',
        ])
        return self.inject_file(keyfile, key_data)

    def inject_files(self, injected_files):
        if self._skip_inject_files_at_boot():
            LOG.debug(_("Skipping agent file injection for this image."),
                      instance=self.instance)
        else:
            for path, contents in injected_files:
                self.inject_file(path, contents)

    def inject_file(self, path, contents):
        LOG.debug(_('Injecting file path: %r'), path, instance=self.instance)

        # Files/paths must be base64-encoded for transmission to agent
        b64_path = base64.b64encode(path)
        b64_contents = base64.b64encode(contents)

        args = {'b64_path': b64_path, 'b64_contents': b64_contents}
        return self._call_agent('inject_file', args)

    def resetnetwork(self):
        LOG.debug(_('Resetting network'), instance=self.instance)

        #NOTE(johngarbutt) old FreeBSD and Gentoo agents return 500 on success
        return self._call_agent('resetnetwork',
                                timeout=CONF.agent_resetnetwork_timeout,
                                success_codes=['0', '500'])

    def _skip_ssh_key_inject(self):
        return self._get_sys_meta_key(SKIP_SSH_SM_KEY)

    def _skip_inject_files_at_boot(self):
        return self._get_sys_meta_key(SKIP_FILES_AT_BOOT_SM_KEY)

    def _get_sys_meta_key(self, key):
        sys_meta = utils.instance_sys_meta(self.instance)
        raw_value = sys_meta.get(key, 'False')
        return strutils.bool_from_string(raw_value, strict=False)


def find_guest_agent(base_dir):
    """
    tries to locate a guest agent at the path
    specificed by agent_rel_path
    """
    if CONF.xenapi_disable_agent:
        return False

    agent_rel_path = CONF.xenapi_agent_path
    agent_path = os.path.join(base_dir, agent_rel_path)
    if os.path.isfile(agent_path):
        # The presence of the guest agent
        # file indicates that this instance can
        # reconfigure the network from xenstore data,
        # so manipulation of files in /etc is not
        # required
        LOG.info(_('XenServer tools installed in this '
                   'image are capable of network injection.  '
                   'Networking files will not be'
                   'manipulated'))
        return True
    xe_daemon_filename = os.path.join(base_dir,
        'usr', 'sbin', 'xe-daemon')
    if os.path.isfile(xe_daemon_filename):
        LOG.info(_('XenServer tools are present '
                   'in this image but are not capable '
                   'of network injection'))
    else:
        LOG.info(_('XenServer tools are not '
                   'installed in this image'))
    return False


def should_use_agent(instance):
    sys_meta = utils.instance_sys_meta(instance)
    if USE_AGENT_SM_KEY not in sys_meta:
        return CONF.xenapi_use_agent_default
    else:
        use_agent_raw = sys_meta[USE_AGENT_SM_KEY]
        try:
            return strutils.bool_from_string(use_agent_raw, strict=True)
        except ValueError:
            LOG.warn(_("Invalid 'agent_present' value. "
                       "Falling back to the default."),
                       instance=instance)
            return CONF.xenapi_use_agent_default


class SimpleDH(object):
    """
    This class wraps all the functionality needed to implement
    basic Diffie-Hellman-Merkle key exchange in Python. It features
    intelligent defaults for the prime and base numbers needed for the
    calculation, while allowing you to supply your own. It requires that
    the openssl binary be installed on the system on which this is run,
    as it uses that to handle the encryption and decryption. If openssl
    is not available, a RuntimeError will be raised.
    """
    def __init__(self):
        self._prime = 162259276829213363391578010288127
        self._base = 5
        self._public = None
        self._shared = None
        self.generate_private()

    def generate_private(self):
        self._private = int(binascii.hexlify(os.urandom(10)), 16)
        return self._private

    def get_public(self):
        self._public = pow(self._base, self._private, self._prime)
        return self._public

    def compute_shared(self, other):
        self._shared = pow(other, self._private, self._prime)
        return self._shared

    def _run_ssl(self, text, decrypt=False):
        cmd = ['openssl', 'aes-128-cbc', '-A', '-a', '-pass',
               'pass:%s' % self._shared, '-nosalt']
        if decrypt:
            cmd.append('-d')
        out, err = utils.execute(*cmd, process_input=text)
        if err:
            raise RuntimeError(_('OpenSSL error: %s') % err)
        return out

    def encrypt(self, text):
        return self._run_ssl(text).strip('\n')

    def decrypt(self, text):
        return self._run_ssl(text, decrypt=True)
