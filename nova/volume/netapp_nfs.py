# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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
Volume driver for NetApp NFS storage.
"""

import os
import suds
import time

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.volume.netapp import netapp_opts
from nova.volume import nfs

from suds.sax import text

LOG = logging.getLogger(__name__)

netapp_nfs_opts = [
    cfg.IntOpt('synchronous_snapshot_create',
               default=0,
               help='Does snapshot creation call returns immediately')
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(netapp_opts)
FLAGS.register_opts(netapp_nfs_opts)


class NetAppNFSDriver(nfs.NfsDriver):
    """Executes commands relating to Volumes."""
    def __init__(self, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self._execute = None
        self._context = None
        super(NetAppNFSDriver, self).__init__(*args, **kwargs)

    def set_execute(self, execute):
        self._execute = execute

    def do_setup(self, context):
        self._context = context
        self.check_for_setup_error()
        self._client = NetAppNFSDriver._get_client()

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        NetAppNFSDriver._check_dfm_flags()
        super(NetAppNFSDriver, self).check_for_setup_error()

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        vol_size = volume.size
        snap_size = snapshot.volume_size

        if vol_size != snap_size:
            msg = _('Cannot create volume of size %(vol_size)s from '
                'snapshot of size %(snap_size)s')
            raise exception.NovaException(msg % locals())

        self._clone_volume(snapshot.name, volume.name, snapshot.volume_id)
        share = self._get_volume_location(snapshot.volume_id)

        return {'provider_location': share}

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self._clone_volume(snapshot['volume_name'],
                           snapshot['name'],
                           snapshot['volume_id'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        nfs_mount = self._get_provider_location(snapshot.volume_id)

        if self._volume_not_present(nfs_mount, snapshot.name):
            return True

        self._execute('rm', self._get_volume_path(nfs_mount, snapshot.name),
                      run_as_root=True)

    @staticmethod
    def _check_dfm_flags():
        """Raises error if any required configuration flag for OnCommand proxy
        is missing."""
        required_flags = ['netapp_wsdl_url',
                          'netapp_login',
                          'netapp_password',
                          'netapp_server_hostname',
                          'netapp_server_port']
        for flag in required_flags:
            if not getattr(FLAGS, flag, None):
                raise exception.NovaException(_('%s is not set') % flag)

    @staticmethod
    def _get_client():
        """Creates SOAP _client for ONTAP-7 DataFabric Service."""
        client = suds.client.Client(FLAGS.netapp_wsdl_url,
                                    username=FLAGS.netapp_login,
                                    password=FLAGS.netapp_password)
        soap_url = 'http://%s:%s/apis/soap/v1' % (
                                          FLAGS.netapp_server_hostname,
                                          FLAGS.netapp_server_port)
        client.set_options(location=soap_url)

        return client

    def _get_volume_location(self, volume_id):
        """Returns NFS mount address as <nfs_ip_address>:<nfs_mount_dir>"""
        nfs_server_ip = self._get_host_ip(volume_id)
        export_path = self._get_export_path(volume_id)
        return (nfs_server_ip + ':' + export_path)

    def _clone_volume(self, volume_name, clone_name, volume_id):
        """Clones mounted volume with OnCommand proxy API"""
        host_id = self._get_host_id(volume_id)
        export_path = self._get_full_export_path(volume_id, host_id)

        request = self._client.factory.create('Request')
        request.Name = 'clone-start'

        clone_start_args = ('<source-path>%s/%s</source-path>'
                            '<destination-path>%s/%s</destination-path>')

        request.Args = text.Raw(clone_start_args % (export_path,
                                                    volume_name,
                                                    export_path,
                                                    clone_name))

        resp = self._client.service.ApiProxy(Target=host_id,
                                            Request=request)

        if resp.Status == 'passed' and FLAGS.synchronous_snapshot_create:
            clone_id = resp.Results['clone-id'][0]
            clone_id_info = clone_id['clone-id-info'][0]
            clone_operation_id = int(clone_id_info['clone-op-id'][0])

            self._wait_for_clone_finished(clone_operation_id, host_id)
        elif resp.Status == 'failed':
            raise exception.NovaException(resp.Reason)

    def _wait_for_clone_finished(self, clone_operation_id, host_id):
        """
        Polls ONTAP7 for clone status. Returns once clone is finished.
        :param clone_operation_id: Identifier of ONTAP clone operation
        """
        clone_list_options = ('<clone-id>'
                                '<clone-id-info>'
                                  '<clone-op-id>%d</clone-op-id>'
                                  '<volume-uuid></volume-uuid>'
                                '</clone-id>'
                              '</clone-id-info>')

        request = self._client.factory.create('Request')
        request.Name = 'clone-list-status'
        request.Args = text.Raw(clone_list_options % clone_operation_id)

        resp = self._client.service.ApiProxy(Target=host_id, Request=request)

        while resp.Status != 'passed':
            time.sleep(1)
            resp = self._client.service.ApiProxy(Target=host_id,
                                                Request=request)

    def _get_provider_location(self, volume_id):
        """
        Returns provider location for given volume
        :param volume_id:
        """
        volume = self.db.volume_get(self._context, volume_id)
        return volume.provider_location

    def _get_host_ip(self, volume_id):
        """Returns IP address for the given volume"""
        return self._get_provider_location(volume_id).split(':')[0]

    def _get_export_path(self, volume_id):
        """Returns NFS export path for the given volume"""
        return self._get_provider_location(volume_id).split(':')[1]

    def _get_host_id(self, volume_id):
        """Returns ID of the ONTAP-7 host"""
        host_ip = self._get_host_ip(volume_id)
        server = self._client.service

        resp = server.HostListInfoIterStart(ObjectNameOrId=host_ip)
        tag = resp.Tag

        try:
            res = server.HostListInfoIterNext(Tag=tag, Maximum=1)
            if hasattr(res, 'Hosts') and res.Hosts.HostInfo:
                return res.Hosts.HostInfo[0].HostId
        finally:
            server.HostListInfoIterEnd(Tag=tag)

    def _get_full_export_path(self, volume_id, host_id):
        """Returns full path to the NFS share, e.g. /vol/vol0/home"""
        export_path = self._get_export_path(volume_id)
        command_args = '<pathname>%s</pathname>'

        request = self._client.factory.create('Request')
        request.Name = 'nfs-exportfs-storage-path'
        request.Args = text.Raw(command_args % export_path)

        resp = self._client.service.ApiProxy(Target=host_id,
                                            Request=request)

        if resp.Status == 'passed':
            return resp.Results['actual-pathname'][0]
        elif resp.Status == 'failed':
            raise exception.NovaException(resp.Reason)

    def _volume_not_present(self, nfs_mount, volume_name):
        """
        Check if volume exists
        """
        try:
            self._try_execute('ls', self._get_volume_path(nfs_mount,
                                                          volume_name))
        except exception.ProcessExecutionError:
            # If the volume isn't present
            return True
        return False

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
                return True
            except exception.ProcessExecutionError:
                tries = tries + 1
                if tries >= FLAGS.num_shell_tries:
                    raise
                LOG.exception(_("Recovering from a failed execute.  "
                                "Try number %s"), tries)
                time.sleep(tries ** 2)

    def _get_volume_path(self, nfs_share, volume_name):
        """Get volume path (local fs path) for given volume name on given nfs
        share
        @param nfs_share string, example 172.18.194.100:/var/nfs
        @param volume_name string,
            example volume-91ee65ec-c473-4391-8c09-162b00c68a8c
        """
        return os.path.join(self._get_mount_point_for_share(nfs_share),
                            volume_name)
