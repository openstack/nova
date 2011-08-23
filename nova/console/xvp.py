# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

import fcntl
import os
import signal

from Cheetah import Template

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('console_xvp_conf_template',
                    utils.abspath('console/xvp.conf.template'),
                    'XVP conf template')
flags.DEFINE_string('console_xvp_conf',
                    '/etc/xvp.conf',
                    'generated XVP conf file')
flags.DEFINE_string('console_xvp_pid',
                    '/var/run/xvp.pid',
                    'XVP master process pid file')
flags.DEFINE_string('console_xvp_log',
                    '/var/log/xvp.log',
                    'XVP log file')
flags.DEFINE_integer('console_xvp_multiplex_port',
                     5900,
                     'port for XVP to multiplex VNC connections on')


class XVPConsoleProxy(object):
    """Sets up XVP config, and manages XVP daemon."""

    def __init__(self):
        self.xvpconf_template = open(FLAGS.console_xvp_conf_template).read()
        self.host = FLAGS.host  # default, set by manager.
        super(XVPConsoleProxy, self).__init__()

    @property
    def console_type(self):
        return 'vnc+xvp'

    def get_port(self, context):
        """Get available port for consoles that need one."""
        #TODO(mdragon): implement port selection for non multiplex ports,
        #               we are not using that, but someone else may want
        #               it.
        return FLAGS.console_xvp_multiplex_port

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
        logging.debug(_('Rebuilding xvp conf'))
        pools = [pool for pool in
                 db.console_pool_get_all_by_host_type(context, self.host,
                                                       self.console_type)
                  if pool['consoles']]
        if not pools:
            logging.debug('No console pools!')
            self._xvp_stop()
            return
        conf_data = {'multiplex_port': FLAGS.console_xvp_multiplex_port,
                     'pools': pools,
                     'pass_encode': self.fix_console_password}
        config = str(Template.Template(self.xvpconf_template,
                                       searchList=[conf_data]))
        self._write_conf(config)
        self._xvp_restart()

    def _write_conf(self, config):
        logging.debug(_('Re-wrote %s') % FLAGS.console_xvp_conf)
        with open(FLAGS.console_xvp_conf, 'w') as cfile:
            cfile.write(config)

    def _xvp_stop(self):
        logging.debug(_('Stopping xvp'))
        pid = self._xvp_pid()
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            #if it's already not running, no problem.
            pass

    def _xvp_start(self):
        if self._xvp_check_running():
            return
        logging.debug(_('Starting xvp'))
        try:
            utils.execute('xvp',
                          '-p', FLAGS.console_xvp_pid,
                          '-c', FLAGS.console_xvp_conf,
                          '-l', FLAGS.console_xvp_log)
        except exception.ProcessExecutionError, err:
            logging.error(_('Error starting xvp: %s') % err)

    def _xvp_restart(self):
        logging.debug(_('Restarting xvp'))
        if not self._xvp_check_running():
            logging.debug(_('xvp not running...'))
            self._xvp_start()
        else:
            pid = self._xvp_pid()
            os.kill(pid, signal.SIGUSR1)

    def _xvp_pid(self):
        try:
            with open(FLAGS.console_xvp_pid, 'r') as pidfile:
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
            - is_pool_password: True if this this is the XenServer api password
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
        #xvp will blow up on passwords that are too long (mdragon)
        password = password[:maxlen]
        out, err = utils.execute('xvp', flag, process_input=password)
        return out.strip()
