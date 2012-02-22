# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 Nexenta Systems, Inc.
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
:mod:`nexenta.volume` -- Driver to store volumes on Nexenta Appliance
=====================================================================

.. automodule:: nexenta.volume
.. moduleauthor:: Yuriy Taraday <yorik.sar@gmail.com>
"""

from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova.volume import driver
from nova.volume import nexenta
from nova.volume.nexenta import jsonrpc

LOG = logging.getLogger("nova.volume.nexenta.volume")
FLAGS = flags.FLAGS

nexenta_opts = [
    cfg.StrOpt('nexenta_host',
              default='',
              help='IP address of Nexenta SA'),
    cfg.IntOpt('nexenta_rest_port',
               default=2000,
               help='HTTP port to connect to Nexenta REST API server'),
    cfg.StrOpt('nexenta_rest_protocol',
               default='auto',
               help='Use http or https for REST connection (default auto)'),
    cfg.StrOpt('nexenta_user',
               default='admin',
               help='User name to connect to Nexenta SA'),
    cfg.StrOpt('nexenta_password',
               default='nexenta',
               help='Password to connect to Nexenta SA'),
    cfg.IntOpt('nexenta_iscsi_target_portal_port',
               default=3260,
               help='Nexenta target portal port'),
    cfg.StrOpt('nexenta_volume',
               default='nova',
               help='pool on SA that will hold all volumes'),
    cfg.StrOpt('nexenta_target_prefix',
               default='iqn.1986-03.com.sun:02:nova-',
               help='IQN prefix for iSCSI targets'),
    cfg.StrOpt('nexenta_target_group_prefix',
               default='nova/',
               help='prefix for iSCSI target groups on SA'),
    cfg.StrOpt('nexenta_blocksize',
               default='',
               help='block size for volumes (blank=default,8KB)'),
    cfg.BoolOpt('nexenta_sparse',
                default=False,
                help='flag to create sparse volumes'),
]
FLAGS.register_opts(nexenta_opts)


class NexentaDriver(driver.ISCSIDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance."""

    def __init__(self):
        super(NexentaDriver, self).__init__()

    def do_setup(self, context):
        protocol = FLAGS.nexenta_rest_protocol
        auto = protocol == 'auto'
        if auto:
            protocol = 'http'
        self.nms = jsonrpc.NexentaJSONProxy(
            '%s://%s:%s/rest/nms/' % (protocol, FLAGS.nexenta_host,
                                      FLAGS.nexenta_rest_port),
            FLAGS.nexenta_user, FLAGS.nexenta_password, auto=auto)

    def check_for_setup_error(self):
        """Verify that the volume for our zvols exists.

        :raise: :py:exc:`LookupError`
        """
        if not self.nms.volume.object_exists(FLAGS.nexenta_volume):
            raise LookupError(_("Volume %s does not exist in Nexenta SA"),
                                    FLAGS.nexenta_volume)

    @staticmethod
    def _get_zvol_name(volume_name):
        """Return zvol name that corresponds given volume name."""
        return '%s/%s' % (FLAGS.nexenta_volume, volume_name)

    @staticmethod
    def _get_target_name(volume_name):
        """Return iSCSI target name to access volume."""
        return '%s%s' % (FLAGS.nexenta_target_prefix, volume_name)

    @staticmethod
    def _get_target_group_name(volume_name):
        """Return Nexenta iSCSI target group name for volume."""
        return '%s%s' % (FLAGS.nexenta_target_group_prefix, volume_name)

    def create_volume(self, volume):
        """Create a zvol on appliance.

        :param volume: volume reference
        """
        self.nms.zvol.create(
            self._get_zvol_name(volume['name']),
            '%sG' % (volume['size'],),
            FLAGS.nexenta_blocksize, FLAGS.nexenta_sparse)

    def delete_volume(self, volume):
        """Destroy a zvol on appliance.

        :param volume: volume reference
        """
        try:
            self.nms.zvol.destroy(self._get_zvol_name(volume['name']), '')
        except nexenta.NexentaException as exc:
            if "zvol has children" in exc.args[1]:
                raise exception.VolumeIsBusy
            else:
                raise

    def create_snapshot(self, snapshot):
        """Create snapshot of existing zvol on appliance.

        :param snapshot: shapshot reference
        """
        self.nms.zvol.create_snapshot(
            self._get_zvol_name(snapshot['volume_name']),
            snapshot['name'], '')

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        self.nms.zvol.clone(
            '%s@%s' % (self._get_zvol_name(snapshot['volume_name']),
                       snapshot['name']),
            self._get_zvol_name(volume['name']))

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: shapshot reference
        """
        try:
            self.nms.snapshot.destroy(
                '%s@%s' % (self._get_zvol_name(snapshot['volume_name']),
                           snapshot['name']),
                '')
        except nexenta.NexentaException as exc:
            if "snapshot has dependent clones" in exc.args[1]:
                raise exception.SnapshotIsBusy
            else:
                raise

    def local_path(self, volume):
        """Return local path to existing local volume.

        We never have local volumes, so it raises NotImplementedError.

        :raise: :py:exc:`NotImplementedError`
        """
        LOG.error(_("Call to local_path should not happen."
                        " Verify that use_local_volumes flag is turned off."))
        raise NotImplementedError

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get zvol exported as LUN 0 at separate target.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        :return: iscsiadm-formatted provider location string
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_name = self._get_target_name(volume['name'])
        target_group_name = self._get_target_group_name(volume['name'])

        try:
            self.nms.iscsitarget.create_target({'target_name': target_name})
        except nexenta.NexentaException as exc:
            if not ensure or 'already configured' not in exc.args[1]:
                raise
            else:
                LOG.info(_('Ignored target creation error "%s"'
                                             ' while ensuring export'), exc)
        try:
            self.nms.stmf.create_targetgroup(target_group_name)
        except nexenta.NexentaException as exc:
            if not ensure or 'already exists' not in exc.args[1]:
                raise
            else:
                LOG.info(_('Ignored target group creation error "%s"'
                                             ' while ensuring export'), exc)
        try:
            self.nms.stmf.add_targetgroup_member(target_group_name,
                                                 target_name)
        except nexenta.NexentaException as exc:
            if not ensure or 'already exists' not in exc.args[1]:
                raise
            else:
                LOG.info(_('Ignored target group member addition error "%s"'
                                             ' while ensuring export'), exc)
        try:
            self.nms.scsidisk.create_lu(zvol_name, {})
        except nexenta.NexentaException as exc:
            if not ensure or 'in use' not in exc.args[1]:
                raise
            else:
                LOG.info(_('Ignored LU creation error "%s"'
                                             ' while ensuring export'), exc)
        try:
            self.nms.scsidisk.add_lun_mapping_entry(zvol_name, {
                'target_group': target_group_name,
                'lun': '0'})
        except nexenta.NexentaException as exc:
            if not ensure or 'view entry exists' not in exc.args[1]:
                raise
            else:
                LOG.info(_('Ignored LUN mapping entry addition error "%s"'
                                             ' while ensuring export'), exc)
        return '%s:%s,1 %s' % (FLAGS.nexenta_host,
                               FLAGS.nexenta_iscsi_target_portal_port,
                               target_name)

    def create_export(self, _ctx, volume):
        """Create new export for zvol.

        :param volume: reference of volume to be exported
        :return: iscsiadm-formatted provider location string
        """
        loc = self._do_export(_ctx, volume, ensure=False)
        return {'provider_location': loc}

    def ensure_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        self._do_export(_ctx, volume, ensure=True)

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export zvol.

        :param volume: reference of volume to be unexported
        """
        zvol_name = self._get_zvol_name(volume['name'])
        target_name = self._get_target_name(volume['name'])
        target_group_name = self._get_target_group_name(volume['name'])
        self.nms.scsidisk.delete_lu(zvol_name)

        try:
            self.nms.stmf.destroy_targetgroup(target_group_name)
        except nexenta.NexentaException as exc:
            # We assume that target group is already gone
            LOG.warn(_('Got error trying to destroy target group'
                ' %(target_group)s, assuming it is already gone: %(exc)s'),
                {'target_group': target_group_name, 'exc': exc})
        try:
            self.nms.iscsitarget.delete_target(target_name)
        except nexenta.NexentaException as exc:
            # We assume that target is gone as well
            LOG.warn(_('Got error trying to delete target %(target)s,'
                ' assuming it is already gone: %(exc)s'),
                {'target': target_name, 'exc': exc})
