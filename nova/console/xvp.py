# Copyright (c) 2010 OpenStack Foundation
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

"""XVP (Xenserver VNC Proxy) driver."""

import os
import signal

import jinja2
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

import nova.conf
from nova import context
from nova import db
from nova.i18n import _
from nova import utils


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class XVPConsoleProxy(object):
    """Sets up XVP config, and manages XVP daemon."""

    def __init__(self):
        self.xvpconf_template = open(CONF.xvp.console_xvp_conf_template).read()
        self.host = CONF.host  # default, set by manager.
        super(XVPConsoleProxy, self).__init__()

    @property
    def console_type(self):
        return 'vnc+xvp'

    def get_port(self, context):
        """Get available port for consoles that need one."""
        # TODO(mdragon): implement port selection for non multiplex ports,
        #               we are not using that, but someone else may want
        #               it.
        return CONF.xvp.console_xvp_multiplex_port

    def setup_console(self, context, console):
        """Sets up actual proxies."""
        self._rebuild_xvp_conf(context.elevated())

    def teardown_console(self, context, console):
        """Tears down actual proxies."""
        self._rebuild_xvp_conf(context.elevated())

    def init_host(self):
        """Start up any config'ed consoles on start."""
        ctxt = context.get_admin_context()
        self._rebuild_xvp_conf(ctxt)

    def fix_pool_password(self, password):
        """Trim password to length, and encode."""
        return self._xvp_encrypt(password, is_pool_password=True)

    def fix_console_password(self, password):
        """Trim password to length, and encode."""
        return self._xvp_encrypt(password)

    def _rebuild_xvp_conf(self, context):
        LOG.debug('Rebuilding xvp conf')
        pools = [pool for pool in
                 db.console_pool_get_all_by_host_type(context, self.host,
                                                       self.console_type)
                  if pool['consoles']]
        if not pools:
            LOG.debug('No console pools!')
            self._xvp_stop()
            return
        conf_data = {'multiplex_port': CONF.xvp.console_xvp_multiplex_port,
                     'pools': pools}
        tmpl_path, tmpl_file = os.path.split(CONF.injected_network_template)
        env = jinja2.Environment(  # nosec
            loader=jinja2.FileSystemLoader(tmpl_path))  # nosec
        env.filters['pass_encode'] = self.fix_console_password
        template = env.get_template(tmpl_file)
        self._write_conf(template.render(conf_data))
        self._xvp_restart()

    def _write_conf(self, config):
        try:
            LOG.debug('Re-wrote %s', CONF.xvp.console_xvp_conf)
            with open(CONF.xvp.console_xvp_conf, 'w') as cfile:
                cfile.write(config)
        except IOError:
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to write configuration file")

    def _xvp_stop(self):
        LOG.debug('Stopping xvp')
        pid = self._xvp_pid()
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            # if it's already not running, no problem.
            pass

    def _xvp_start(self):
        if self._xvp_check_running():
            return
        LOG.debug('Starting xvp')
        try:
            utils.execute('xvp',
                          '-p', CONF.xvp.console_xvp_pid,
                          '-c', CONF.xvp.console_xvp_conf,
                          '-l', CONF.xvp.console_xvp_log)
        except processutils.ProcessExecutionError as err:
            LOG.error('Error starting xvp: %s', err)

    def _xvp_restart(self):
        LOG.debug('Restarting xvp')
        if not self._xvp_check_running():
            LOG.debug('xvp not running...')
            self._xvp_start()
        else:
            pid = self._xvp_pid()
            os.kill(pid, signal.SIGUSR1)

    def _xvp_pid(self):
        try:
            with open(CONF.xvp.console_xvp_pid, 'r') as pidfile:
                pid = int(pidfile.read())
        except IOError:
            return None
        except ValueError:
            return None
        return pid

    def _xvp_check_running(self):
        pid = self._xvp_pid()
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _xvp_encrypt(self, password, is_pool_password=False):
        """Call xvp to obfuscate passwords for config file.

        Args:
            - password: the password to encode, max 8 char for vm passwords,
                        and 16 chars for pool passwords. passwords will
                        be trimmed to max len before encoding.
            - is_pool_password: True if this is the XenServer api password
                                False if it's a VM console password
              (xvp uses different keys and max lengths for pool passwords)

        Note that xvp's obfuscation should not be considered 'real' encryption.
        It simply DES encrypts the passwords with static keys plainly viewable
        in the xvp source code.

        """
        maxlen = 8
        flag = '-e'
        if is_pool_password:
            maxlen = 16
            flag = '-x'
        # xvp will blow up on passwords that are too long (mdragon)
        password = password[:maxlen]
        out, err = utils.execute('xvp', flag, process_input=password)
        if err:
            raise processutils.ProcessExecutionError(_("Failed to run xvp."))
        return out.strip()
