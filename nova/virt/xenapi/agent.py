# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010-2012 OpenStack LLC.
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

from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova import utils


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
]

FLAGS = flags.FLAGS
FLAGS.register_opts(xenapi_agent_opts)


def _call_agent(session, instance, vm_ref, method, addl_args=None,
                timeout=None):
    """Abstracts out the interaction with the agent xenapi plugin."""
    if addl_args is None:
        addl_args = {}
    if timeout is None:
        timeout = FLAGS.agent_timeout

    vm_rec = session.call_xenapi("VM.get_record", vm_ref)

    args = {
        'id': str(uuid.uuid4()),
        'dom_id': vm_rec['domid'],
        'timeout': str(timeout),
    }
    args.update(addl_args)

    try:
        ret = session.call_plugin('agent', method, args)
    except session.XenAPI.Failure, e:
        err_msg = e.details[-1].splitlines()[-1]
        if 'TIMEOUT:' in err_msg:
            LOG.error(_('TIMEOUT: The call to %(method)s timed out. '
                        'args=%(args)r'), locals(), instance=instance)
            return {'returncode': 'timeout', 'message': err_msg}
        elif 'NOT IMPLEMENTED:' in err_msg:
            LOG.error(_('NOT IMPLEMENTED: The call to %(method)s is not'
                        ' supported by the agent. args=%(args)r'),
                      locals(), instance=instance)
            return {'returncode': 'notimplemented', 'message': err_msg}
        else:
            LOG.error(_('The call to %(method)s returned an error: %(e)s. '
                        'args=%(args)r'), locals(), instance=instance)
            return {'returncode': 'error', 'message': err_msg}
        return None

    if isinstance(ret, dict):
        return ret
    try:
        return jsonutils.loads(ret)
    except TypeError:
        LOG.error(_('The agent call to %(method)s returned an invalid'
                    ' response: %(ret)r. path=%(path)s; args=%(args)r'),
                  locals(), instance=instance)
        return {'returncode': 'error',
                'message': 'unable to deserialize response'}


def _get_agent_version(session, instance, vm_ref):
    resp = _call_agent(session, instance, vm_ref, 'version')
    if resp['returncode'] != '0':
        LOG.error(_('Failed to query agent version: %(resp)r'),
                  locals(), instance=instance)
        return None

    # Some old versions of the Windows agent have a trailing \\r\\n
    # (ie CRLF escaped) for some reason. Strip that off.
    return resp['message'].replace('\\r\\n', '')


def get_agent_version(session, instance, vm_ref):
    """Get the version of the agent running on the VM instance."""

    LOG.debug(_('Querying agent version'), instance=instance)

    # The agent can be slow to start for a variety of reasons. On Windows,
    # it will generally perform a setup process on first boot that can
    # take a couple of minutes and then reboot. On Linux, the system can
    # also take a while to boot. So we need to be more patient than
    # normal as well as watch for domid changes

    expiration = time.time() + FLAGS.agent_version_timeout
    while time.time() < expiration:
        ret = _get_agent_version(session, instance, vm_ref)
        if ret:
            return ret

    LOG.info(_('Reached maximum time attempting to query agent version'),
             instance=instance)

    return None


def agent_update(session, instance, vm_ref, agent_build):
    """Update agent on the VM instance."""

    LOG.info(_('Updating agent to %s'), agent_build['version'],
             instance=instance)

    # Send the encrypted password
    args = {'url': agent_build['url'], 'md5sum': agent_build['md5hash']}
    resp = _call_agent(session, instance, vm_ref, 'agentupdate', args)
    if resp['returncode'] != '0':
        LOG.error(_('Failed to update agent: %(resp)r'), locals(),
                  instance=instance)
        return None
    return resp['message']


def set_admin_password(session, instance, vm_ref, new_pass):
    """Set the root/admin password on the VM instance.

    This is done via an agent running on the VM. Communication between nova
    and the agent is done via writing xenstore records. Since communication
    is done over the XenAPI RPC calls, we need to encrypt the password.
    We're using a simple Diffie-Hellman class instead of a more advanced
    library (such as M2Crypto) for compatibility with the agent code.
    """
    LOG.debug(_('Setting admin password'), instance=instance)

    dh = SimpleDH()

    # Exchange keys
    args = {'pub': str(dh.get_public())}
    resp = _call_agent(session, instance, vm_ref, 'key_init', args)

    # Successful return code from key_init is 'D0'
    if resp['returncode'] != 'D0':
        msg = _('Failed to exchange keys: %(resp)r') % locals()
        LOG.error(msg, instance=instance)
        raise Exception(msg)

    # Some old versions of the Windows agent have a trailing \\r\\n
    # (ie CRLF escaped) for some reason. Strip that off.
    agent_pub = int(resp['message'].replace('\\r\\n', ''))
    dh.compute_shared(agent_pub)

    # Some old versions of Linux and Windows agent expect trailing \n
    # on password to work correctly.
    enc_pass = dh.encrypt(new_pass + '\n')

    # Send the encrypted password
    args = {'enc_pass': enc_pass}
    resp = _call_agent(session, instance, vm_ref, 'password', args)

    # Successful return code from password is '0'
    if resp['returncode'] != '0':
        msg = _('Failed to update password: %(resp)r') % locals()
        LOG.error(msg, instance=instance)
        raise Exception(msg)

    return resp['message']


def inject_file(session, instance, vm_ref, path, contents):
    LOG.debug(_('Injecting file path: %r'), path, instance=instance)

    # Files/paths must be base64-encoded for transmission to agent
    b64_path = base64.b64encode(path)
    b64_contents = base64.b64encode(contents)

    args = {'b64_path': b64_path, 'b64_contents': b64_contents}

    # If the agent doesn't support file injection, a NotImplementedError
    # will be raised with the appropriate message.
    resp = _call_agent(session, instance, vm_ref, 'inject_file', args)
    if resp['returncode'] != '0':
        LOG.error(_('Failed to inject file: %(resp)r'), locals(),
                  instance=instance)
        return None

    return resp['message']


def resetnetwork(session, instance, vm_ref):
    LOG.debug(_('Resetting network'), instance=instance)

    resp = _call_agent(session, instance, vm_ref, 'resetnetwork',
                       timeout=FLAGS.agent_resetnetwork_timeout)
    if resp['returncode'] != '0':
        LOG.error(_('Failed to reset network: %(resp)r'), locals(),
                  instance=instance)
        return None

    return resp['message']


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
        self._public = self.mod_exp(self._base, self._private, self._prime)
        return self._public

    def compute_shared(self, other):
        self._shared = self.mod_exp(other, self._private, self._prime)
        return self._shared

    @staticmethod
    def mod_exp(num, exp, mod):
        """Efficient implementation of (num ** exp) % mod"""
        result = 1
        while exp > 0:
            if (exp & 1) == 1:
                result = (result * num) % mod
            exp = exp >> 1
            num = (num * num) % mod
        return result

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
