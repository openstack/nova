# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Helper code for the iSCSI volume driver.

"""

from nova import flags
from nova.openstack.common import cfg
from nova import utils


iscsi_helper_opt = \
    cfg.StrOpt('iscsi_helper',
               default='ietadm',
               help='iscsi target user-land tool to use')

FLAGS = flags.FLAGS
FLAGS.add_option(iscsi_helper_opt)


class TargetAdmin(object):
    """iSCSI target administration.

    Base class for iSCSI target admin helpers.
    """

    def __init__(self, cmd, execute):
        self._cmd = cmd
        self.set_execute(execute)

    def set_execute(self, execute):
        """Set the function to be used to execute commands."""
        self._execute = execute

    def _run(self, *args, **kwargs):
        self._execute(self._cmd, *args, run_as_root=True, **kwargs)

    def new_target(self, name, tid, **kwargs):
        """Create a new iSCSI target."""
        raise NotImplementedError()

    def delete_target(self, tid, **kwargs):
        """Delete a target."""
        raise NotImplementedError()

    def show_target(self, tid, **kwargs):
        """Query the given target ID."""
        raise NotImplementedError()

    def new_logicalunit(self, tid, lun, path, **kwargs):
        """Create a new LUN on a target using the supplied path."""
        raise NotImplementedError()

    def delete_logicalunit(self, tid, lun, **kwargs):
        """Delete a logical unit from a target."""
        raise NotImplementedError()


class TgtAdm(TargetAdmin):
    """iSCSI target administration using tgtadm."""

    def __init__(self, execute=utils.execute):
        super(TgtAdm, self).__init__('tgtadm', execute)

    def new_target(self, name, tid, **kwargs):
        self._run('--op', 'new',
                  '--lld=iscsi', '--mode=target',
                  '--tid=%s' % tid,
                  '--targetname=%s' % name,
                  **kwargs)
        self._run('--op', 'bind',
                  '--lld=iscsi', '--mode=target',
                  '--initiator-address=ALL',
                  '--tid=%s' % tid,
                  **kwargs)

    def delete_target(self, tid, **kwargs):
        self._run('--op', 'delete',
                  '--lld=iscsi', '--mode=target',
                  '--tid=%s' % tid,
                  **kwargs)

    def show_target(self, tid, **kwargs):
        self._run('--op', 'show',
                  '--lld=iscsi', '--mode=target',
                  '--tid=%s' % tid,
                  **kwargs)

    def new_logicalunit(self, tid, lun, path, **kwargs):
        self._run('--op', 'new',
                  '--lld=iscsi', '--mode=logicalunit',
                  '--tid=%s' % tid,
                  '--lun=%d' % (lun + 1),  # lun0 is reserved
                  '--backing-store=%s' % path,
                  **kwargs)

    def delete_logicalunit(self, tid, lun, **kwargs):
        self._run('--op', 'delete',
                  '--lld=iscsi', '--mode=logicalunit',
                  '--tid=%s' % tid,
                  '--lun=%d' % (lun + 1),
                  **kwargs)


class IetAdm(TargetAdmin):
    """iSCSI target administration using ietadm."""

    def __init__(self, execute=utils.execute):
        super(IetAdm, self).__init__('ietadm', execute)

    def new_target(self, name, tid, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--params', 'Name=%s' % name,
                  **kwargs)

    def delete_target(self, tid, **kwargs):
        self._run('--op', 'delete',
                  '--tid=%s' % tid,
                  **kwargs)

    def show_target(self, tid, **kwargs):
        self._run('--op', 'show',
                  '--tid=%s' % tid,
                  **kwargs)

    def new_logicalunit(self, tid, lun, path, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--lun=%d' % lun,
                  '--params', 'Path=%s,Type=fileio' % path,
                  **kwargs)

    def delete_logicalunit(self, tid, lun, **kwargs):
        self._run('--op', 'delete',
                  '--tid=%s' % tid,
                  '--lun=%d' % lun,
                  **kwargs)


def get_target_admin():
    if FLAGS.iscsi_helper == 'tgtadm':
        return TgtAdm()
    else:
        return IetAdm()
