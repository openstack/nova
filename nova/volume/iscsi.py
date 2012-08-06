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
import os

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)

iscsi_helper_opt = [
        cfg.StrOpt('iscsi_helper',
                    default='tgtadm',
                    help='iscsi target user-land tool to use'),
        cfg.StrOpt('volumes_dir',
                   default='$state_path/volumes',
                   help='Volume configfuration file storage directory'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(iscsi_helper_opt)


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

    def create_iscsi_target(self, name, tid, lun, path, **kwargs):
        """Create a iSCSI target and logical unit"""
        raise NotImplementedError()

    def remove_iscsi_target(self, tid, lun, vol_id, **kwargs):
        """Remove a iSCSI target and logical unit"""
        raise NotImplementedError()

    def _new_target(self, name, tid, **kwargs):
        """Create a new iSCSI target."""
        raise NotImplementedError()

    def _delete_target(self, tid, **kwargs):
        """Delete a target."""
        raise NotImplementedError()

    def show_target(self, tid, **kwargs):
        """Query the given target ID."""
        raise NotImplementedError()

    def _new_logicalunit(self, tid, lun, path, **kwargs):
        """Create a new LUN on a target using the supplied path."""
        raise NotImplementedError()

    def _delete_logicalunit(self, tid, lun, **kwargs):
        """Delete a logical unit from a target."""
        raise NotImplementedError()


class TgtAdm(TargetAdmin):
    """iSCSI target administration using tgtadm."""

    def __init__(self, execute=utils.execute):
        super(TgtAdm, self).__init__('tgtadm', execute)

    def create_iscsi_target(self, name, tid, lun, path, **kwargs):
        try:
            if not os.path.exists(FLAGS.volumes_dir):
                os.makedirs(FLAGS.volumes_dir)

            # grab the volume id
            vol_id = name.split(':')[1]

            volume_conf = """
                <target %s>
                    backing-store %s
                </target>
            """ % (name, path)

            LOG.info(_('Creating volume: %s') % vol_id)
            volume_path = os.path.join(FLAGS.volumes_dir, vol_id)
            if not os.path.isfile(volume_path):
                f = open(volume_path, 'w+')
                f.write(volume_conf)
                f.close()

            self._execute('tgt-admin', '--execute',
                          '--conf', volume_path,
                          '--update', vol_id, run_as_root=True)

        except Exception as ex:
            LOG.exception(ex)
            raise exception.NovaException(_('Failed to create volume: %s')
                % vol_id)

    def remove_iscsi_target(self, tid, lun, vol_id, **kwargs):
        try:
            LOG.info(_('Removing volume: %s') % vol_id)
            vol_uuid_file = 'volume-%s' % vol_id
            volume_path = os.path.join(FLAGS.volumes_dir, vol_uuid_file)
            if os.path.isfile(volume_path):
                delete_file = '%s%s' % (FLAGS.iscsi_target_prefix,
                                        vol_uuid_file)
                self._execute('tgt-admin',
                              '--delete',
                              delete_file,
                              run_as_root=True)
                os.unlink(volume_path)
        except Exception as ex:
            LOG.exception(ex)
            raise exception.NovaException(_('Failed to remove volume: %s')
                    % vol_id)

    def show_target(self, tid, **kwargs):
        self._run('--op', 'show',
                  '--lld=iscsi', '--mode=target',
                  '--tid=%s' % tid,
                  **kwargs)


class IetAdm(TargetAdmin):
    """iSCSI target administration using ietadm."""

    def __init__(self, execute=utils.execute):
        super(IetAdm, self).__init__('ietadm', execute)

    def create_iscsi_target(self, name, tid, lun, path, **kwargs):
        self._new_target(name, tid, **kwargs)
        self._new_logicalunit(tid, lun, path, **kwargs)

    def remove_iscsi_target(self, tid, lun, vol_id, **kwargs):
        LOG.info(_('Removing volume: %s') % vol_id)
        self._delete_target(tid, **kwargs)
        self._delete_logicalunit(tid, lun, **kwargs)

    def _new_target(self, name, tid, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--params', 'Name=%s' % name,
                  **kwargs)

    def _delete_target(self, tid, **kwargs):
        self._run('--op', 'delete',
                  '--tid=%s' % tid,
                  **kwargs)

    def show_target(self, tid, **kwargs):
        self._run('--op', 'show',
                  '--tid=%s' % tid,
                  **kwargs)

    def _new_logicalunit(self, tid, lun, path, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--lun=%d' % lun,
                  '--params', 'Path=%s,Type=fileio' % path,
                  **kwargs)

    def _delete_logicalunit(self, tid, lun, **kwargs):
        self._run('--op', 'delete',
                  '--tid=%s' % tid,
                  '--lun=%d' % lun,
                  **kwargs)


def get_target_admin():
    if FLAGS.iscsi_helper == 'tgtadm':
        return TgtAdm()
    else:
        return IetAdm()
