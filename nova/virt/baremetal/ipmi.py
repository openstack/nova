# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""
Baremetal IPMI power manager.
"""

import os
import stat
import tempfile

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova import paths
from nova import utils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import base
from nova.virt.baremetal import utils as bm_utils

opts = [
    cfg.StrOpt('terminal',
               default='shellinaboxd',
               help='path to baremetal terminal program'),
    cfg.StrOpt('terminal_cert_dir',
               help='path to baremetal terminal SSL cert(PEM)'),
    cfg.StrOpt('terminal_pid_dir',
               default=paths.state_path_def('baremetal/console'),
               help='path to directory stores pidfiles of baremetal_terminal'),
    cfg.IntOpt('ipmi_power_retry',
               default=10,
               help='maximal number of retries for IPMI operations'),
    ]

baremetal_group = cfg.OptGroup(name='baremetal',
                               title='Baremetal Options')

CONF = cfg.CONF
CONF.register_group(baremetal_group)
CONF.register_opts(opts, baremetal_group)

LOG = logging.getLogger(__name__)


def _make_password_file(password):
    fd, path = tempfile.mkstemp()
    os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(password)
    return path


def _get_console_pid_path(node_id):
    name = "%s.pid" % node_id
    path = os.path.join(CONF.baremetal.terminal_pid_dir, name)
    return path


def _get_console_pid(node_id):
    pid_path = _get_console_pid_path(node_id)
    if os.path.exists(pid_path):
        with open(pid_path, 'r') as f:
            pid_str = f.read()
        try:
            return int(pid_str)
        except ValueError:
            LOG.warn(_("pid file %s does not contain any pid"), pid_path)
    return None


class IPMI(base.PowerManager):
    """IPMI Power Driver for Baremetal Nova Compute

    This PowerManager class provides mechanism for controlling the power state
    of physical hardware via IPMI calls. It also provides serial console access
    where available.

    """

    def __init__(self, node, **kwargs):
        self.state = None
        self.retries = None
        self.node_id = node['id']
        self.address = node['pm_address']
        self.user = node['pm_user']
        self.password = node['pm_password']
        self.port = node['terminal_port']

        if self.node_id == None:
            raise exception.InvalidParameterValue(_("Node id not supplied "
                "to IPMI"))
        if self.address == None:
            raise exception.InvalidParameterValue(_("Address not supplied "
                "to IPMI"))
        if self.user == None:
            raise exception.InvalidParameterValue(_("User not supplied "
                "to IPMI"))
        if self.password == None:
            raise exception.InvalidParameterValue(_("Password not supplied "
                "to IPMI"))

    def _exec_ipmitool(self, command):
        args = ['ipmitool',
                '-I',
                'lanplus',
                '-H',
                self.address,
                '-U',
                self.user,
                '-f']
        pwfile = _make_password_file(self.password)
        try:
            args.append(pwfile)
            args.extend(command.split(" "))
            out, err = utils.execute(*args, attempts=3)
            LOG.debug(_("ipmitool stdout: '%(out)s', stderr: '%(err)s'"),
                      {'out': out, 'err': err})
            return out, err
        finally:
            bm_utils.unlink_without_raise(pwfile)

    def _power_on(self):
        """Turn the power to this node ON."""

        def _wait_for_power_on():
            """Called at an interval until the node's power is on."""

            if self.is_power_on():
                self.state = baremetal_states.ACTIVE
                raise loopingcall.LoopingCallDone()
            if self.retries > CONF.baremetal.ipmi_power_retry:
                LOG.error(_("IPMI power on failed after %d tries") % (
                    CONF.baremetal.ipmi_power_retry))
                self.state = baremetal_states.ERROR
                raise loopingcall.LoopingCallDone()
            try:
                self.retries += 1
                if not self.power_on_called:
                    self._exec_ipmitool("power on")
                    self.power_on_called = True
            except Exception:
                LOG.exception(_("IPMI power on failed"))

        self.retries = 0
        self.power_on_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_on)
        timer.start(interval=1.0).wait()

    def _power_off(self):
        """Turn the power to this node OFF."""

        def _wait_for_power_off():
            """Called at an interval until the node's power is off."""

            if self.is_power_on() is False:
                self.state = baremetal_states.DELETED
                raise loopingcall.LoopingCallDone()
            if self.retries > CONF.baremetal.ipmi_power_retry:
                LOG.error(_("IPMI power off failed after %d tries") % (
                    CONF.baremetal.ipmi_power_retry))
                self.state = baremetal_states.ERROR
                raise loopingcall.LoopingCallDone()
            try:
                self.retries += 1
                if not self.power_off_called:
                    self._exec_ipmitool("power off")
                    self.power_off_called = True
            except Exception:
                LOG.exception(_("IPMI power off failed"))

        self.retries = 0
        self.power_off_called = False
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_power_off)
        timer.start(interval=1.0).wait()

    def _set_pxe_for_next_boot(self):
        try:
            self._exec_ipmitool("chassis bootdev pxe options=persistent")
        except Exception:
            LOG.exception(_("IPMI set next bootdev failed"))

    def activate_node(self):
        """Turns the power to node ON.

        Sets node next-boot to PXE and turns the power on,
        waiting up to ipmi_power_retry/2 seconds for confirmation
        that the power is on.

        :returns: One of baremetal_states.py, representing the new state.
        """
        if self.is_power_on() and self.state == baremetal_states.ACTIVE:
            LOG.warning(_("Activate node called, but node %s "
                          "is already active") % self.address)
        self._set_pxe_for_next_boot()
        self._power_on()
        return self.state

    def reboot_node(self):
        """Cycles the power to a node.

        Turns the power off, sets next-boot to PXE, and turns the power on.
        Each action waits up to ipmi_power_retry/2 seconds for confirmation
        that the power state has changed.

        :returns: One of baremetal_states.py, representing the new state.
        """
        self._power_off()
        self._set_pxe_for_next_boot()
        self._power_on()
        return self.state

    def deactivate_node(self):
        """Turns the power to node OFF.

        Turns the power off, and waits up to ipmi_power_retry/2 seconds
        for confirmation that the power is off.

        :returns: One of baremetal_states.py, representing the new state.
        """
        self._power_off()
        return self.state

    def is_power_on(self):
        """Check if the power is currently on.

        :returns: True if on; False if off; None if unable to determine.
        """
        # NOTE(deva): string matching based on
        #             http://ipmitool.cvs.sourceforge.net/
        #               viewvc/ipmitool/ipmitool/lib/ipmi_chassis.c
        res = self._exec_ipmitool("power status")[0]
        if res == ("Chassis Power is on\n"):
            return True
        elif res == ("Chassis Power is off\n"):
            return False
        return None

    def start_console(self):
        if not self.port:
            return
        args = []
        args.append(CONF.baremetal.terminal)
        if CONF.baremetal.terminal_cert_dir:
            args.append("-c")
            args.append(CONF.baremetal.terminal_cert_dir)
        else:
            args.append("-t")
        args.append("-p")
        args.append(str(self.port))
        args.append("--background=%s" % _get_console_pid_path(self.node_id))
        args.append("-s")

        try:
            pwfile = _make_password_file(self.password)
            ipmi_args = "/:%(uid)s:%(gid)s:HOME:ipmitool -H %(address)s" \
                    " -I lanplus -U %(user)s -f %(pwfile)s sol activate" \
                    % {'uid': os.getuid(),
                       'gid': os.getgid(),
                       'address': self.address,
                       'user': self.user,
                       'pwfile': pwfile,
                       }

            args.append(ipmi_args)
            # Run shellinaboxd without pipes. Otherwise utils.execute() waits
            # infinitely since shellinaboxd does not close passed fds.
            x = ["'" + arg.replace("'", "'\\''") + "'" for arg in args]
            x.append('</dev/null')
            x.append('>/dev/null')
            x.append('2>&1')
            utils.execute(' '.join(x), shell=True)
        finally:
            bm_utils.unlink_without_raise(pwfile)

    def stop_console(self):
        console_pid = _get_console_pid(self.node_id)
        if console_pid:
            # Allow exitcode 99 (RC_UNAUTHORIZED)
            utils.execute('kill', '-TERM', str(console_pid),
                          run_as_root=True,
                          check_exit_code=[0, 99])
        bm_utils.unlink_without_raise(_get_console_pid_path(self.node_id))
