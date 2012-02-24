# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
Volume driver for NetApp storage systems.

This driver requires NetApp OnCommand 5.0 and one or more Data
ONTAP 7-mode storage systems with installed iSCSI licenses.

"""

import time
import string

import suds
from suds import client
from suds.sax import text

from nova import exception
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova.volume import driver

LOG = logging.getLogger("nova.volume.driver")

netapp_opts = [
    cfg.StrOpt('netapp_wsdl_url',
               default=None,
               help='URL of the WSDL file for the DFM server'),
    cfg.StrOpt('netapp_login',
               default=None,
               help='User name for the DFM server'),
    cfg.StrOpt('netapp_password',
               default=None,
               help='Password for the DFM server'),
    cfg.StrOpt('netapp_server_hostname',
               default=None,
               help='Hostname for the DFM server'),
    cfg.IntOpt('netapp_server_port',
               default=8088,
               help='Port number for the DFM server'),
    cfg.StrOpt('netapp_storage_service',
               default=None,
               help='Storage service to use for provisioning'),
    cfg.StrOpt('netapp_vfiler',
               default=None,
               help='Vfiler to use for provisioning'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(netapp_opts)


class NetAppISCSIDriver(driver.ISCSIDriver):
    """NetApp iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(NetAppISCSIDriver, self).__init__(*args, **kwargs)

    def _check_fail(self, request, response):
        if 'failed' == response.Status:
            name = request.Name
            reason = response.Reason
            msg = _('API %(name)sfailed: %(reason)s')
            raise exception.Error(msg % locals())

    def _create_client(self, wsdl_url, login, password, hostname, port):
        """
        Instantiate a "suds" client to make web services calls to the
        DFM server. Note that the WSDL file is quite large and may take
        a few seconds to parse.
        """
        self.client = client.Client(wsdl_url,
                                    username=login,
                                    password=password)
        soap_url = 'http://%s:%s/apis/soap/v1' % (hostname, port)
        self.client.set_options(location=soap_url)

    def _set_storage_service(self, storage_service):
        """Set the storage service to use for provisioning"""
        self.storage_service = storage_service

    def _set_vfiler(self, vfiler):
        """Set the vfiler to use for provisioning"""
        self.vfiler = vfiler

    def _check_flags(self):
        """Ensure that the flags we care about are set."""
        required_flags = ['netapp_wsdl_url', 'netapp_login', 'netapp_password',
                'netapp_server_hostname', 'netapp_server_port',
                'netapp_storage_service']
        for flag in required_flags:
            if not getattr(FLAGS, flag, None):
                raise exception.Error(_('%s is not set') % flag)

    def do_setup(self, context):
        """
        Called one time by the manager after the driver is loaded.
        Validate the flags we care about and setup the suds (web services)
        client.
        """
        self._check_flags()
        self._create_client(FLAGS.netapp_wsdl_url, FLAGS.netapp_login,
            FLAGS.netapp_password, FLAGS.netapp_server_hostname,
            FLAGS.netapp_server_port)
        self._set_storage_service(FLAGS.netapp_storage_service)
        if FLAGS.netapp_vfiler:
            self._set_vfiler(FLAGS.netapp_vfiler)

    def check_for_setup_error(self):
        """Invoke a web services API to make sure we can talk to the server."""
        res = self.client.service.DfmAbout()
        LOG.debug(_("Connected to DFM server"))

    def _get_job_progress(self, job_id):
        """
        Obtain the latest progress report for the job and return the
        list of progress events.
        """
        server = self.client.service
        res = server.DpJobProgressEventListIterStart(JobId=job_id)
        tag = res.Tag
        event_list = []
        try:
            while True:
                res = server.DpJobProgressEventListIterNext(Tag=tag,
                                                            Maximum=100)
                if not hasattr(res, 'ProgressEvents'):
                    break
                event_list += res.ProgressEvents.DpJobProgressEventInfo
        finally:
            server.DpJobProgressEventListIterEnd(Tag=tag)
        return event_list

    def _wait_for_job(self, job_id):
        """
        Poll the job until it completes or an error is detected. Return the
        final list of progress events if it completes successfully.
        """
        while True:
            events = self._get_job_progress(job_id)
            for event in events:
                if event.EventStatus == 'error':
                    raise exception.Error(_('Job failed: %s') %
                        (event.ErrorMessage))
                if event.EventType == 'job-end':
                    return events
            time.sleep(5)

    def _dataset_name(self, project):
        """Return the dataset name for a given project """
        _project = string.replace(string.replace(project, ' ', '_'), '-', '_')
        return 'OpenStack_' + _project

    def _does_dataset_exist(self, dataset_name):
        """Check if a dataset already exists"""
        server = self.client.service
        try:
            res = server.DatasetListInfoIterStart(ObjectNameOrId=dataset_name)
            tag = res.Tag
        except suds.WebFault:
            return False
        try:
            res = server.DatasetListInfoIterNext(Tag=tag, Maximum=1)
            if hasattr(res, 'Datasets') and res.Datasets.DatasetInfo:
                return True
        finally:
            server.DatasetListInfoIterEnd(Tag=tag)
        return False

    def _create_dataset(self, dataset_name):
        """
        Create a new dataset using the storage service. The export settings are
        set to create iSCSI LUNs aligned for Linux.
        """
        server = self.client.service

        lunmap = self.client.factory.create('DatasetLunMappingInfo')
        lunmap.IgroupOsType = 'linux'
        export = self.client.factory.create('DatasetExportInfo')
        export.DatasetExportProtocol = 'iscsi'
        export.DatasetLunMappingInfo = lunmap
        detail = self.client.factory.create('StorageSetInfo')
        detail.DpNodeName = 'Primary data'
        detail.DatasetExportInfo = export
        if hasattr(self, 'vfiler'):
            detail.ServerNameOrId = self.vfiler
        details = self.client.factory.create('ArrayOfStorageSetInfo')
        details.StorageSetInfo = [detail]

        server.StorageServiceDatasetProvision(
                StorageServiceNameOrId=self.storage_service,
                DatasetName=dataset_name,
                AssumeConfirmation=True,
                StorageSetDetails=details)

    def _provision(self, name, description, project, size):
        """
        Provision a LUN through provisioning manager. The LUN will be created
        inside a dataset associated with the project. If the dataset doesn't
        already exist, we create it using the storage service specified in the
        nova conf.
        """

        dataset_name = self._dataset_name(project)
        if not self._does_dataset_exist(dataset_name):
            self._create_dataset(dataset_name)

        info = self.client.factory.create('ProvisionMemberRequestInfo')
        info.Name = name
        if description:
            info.Description = description
        info.Size = size
        info.MaximumSnapshotSpace = 2 * long(size)

        server = self.client.service
        lock_id = server.DatasetEditBegin(DatasetNameOrId=dataset_name)
        try:
            server.DatasetProvisionMember(EditLockId=lock_id,
                                          ProvisionMemberRequestInfo=info)
            res = server.DatasetEditCommit(EditLockId=lock_id,
                                           AssumeConfirmation=True)
        except (suds.WebFault, Exception):
            server.DatasetEditRollback(EditLockId=lock_id)
            raise exception.Error(_('Failed to provision dataset member'))

        lun_id = None

        for info in res.JobIds.JobInfo:
            events = self._wait_for_job(info.JobId)
            for event in events:
                if event.EventType != 'lun-create':
                    continue
                lun_id = event.ProgressLunInfo.LunPathId

        if not lun_id:
            raise exception.Error(_('No LUN was created by the provision job'))

    def _remove_destroy(self, name, project):
        """
        Remove the LUN from the dataset and destroy the actual LUN on the
        storage system.
        """
        lun_id = self._get_lun_id(name, project)
        if not lun_id:
            raise exception.Error(_("Failed to find LUN ID for volume %s") %
                (name))

        member = self.client.factory.create('DatasetMemberParameter')
        member.ObjectNameOrId = lun_id
        members = self.client.factory.create('ArrayOfDatasetMemberParameter')
        members.DatasetMemberParameter = [member]

        dataset_name = self._dataset_name(project)

        server = self.client.service
        lock_id = server.DatasetEditBegin(DatasetNameOrId=dataset_name)
        try:
            server.DatasetRemoveMember(EditLockId=lock_id, Destroy=True,
                                       DatasetMemberParameters=members)
            server.DatasetEditCommit(EditLockId=lock_id,
                                     AssumeConfirmation=True)
        except (suds.WebFault, Exception):
            server.DatasetEditRollback(EditLockId=lock_id)
            msg = _('Failed to remove and delete dataset member')
            raise exception.Error(msg)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume"""
        default_size = '104857600'  # 100 MB
        gigabytes = 1073741824L  # 2^30
        name = volume['name']
        project = volume['project_id']
        display_name = volume['display_name']
        display_description = volume['display_description']
        if display_name:
            if display_description:
                description = display_name + "\n" + display_description
            else:
                description = display_name
        elif display_description:
            description = display_description
        if int(volume['size']) == 0:
            size = default_size
        else:
            size = str(int(volume['size']) * gigabytes)
        self._provision(name, description, project, size)

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes"""
        name = volume['name']
        project = volume['project_id']
        self._remove_destroy(name, project)

    def _get_lun_id(self, name, project):
        """
        Given the name of a volume, find the DFM (OnCommand) ID of the LUN
        corresponding to that volume. Currently we do this by enumerating
        all of the LUNs in the dataset and matching the names against the
        OpenStack volume name.

        This could become a performance bottleneck in very large installations
        in which case possible options for mitigating the problem are:
        1) Store the LUN ID alongside the volume in the nova DB (if possible)
        2) Cache the list of LUNs in the dataset in driver memory
        3) Store the volume to LUN ID mappings in a local file
        """
        dataset_name = self._dataset_name(project)

        server = self.client.service
        res = server.DatasetMemberListInfoIterStart(
                DatasetNameOrId=dataset_name,
                IncludeExportsInfo=True,
                IncludeIndirect=True,
                MemberType='lun_path')
        tag = res.Tag
        suffix = '/' + name
        try:
            while True:
                res = server.DatasetMemberListInfoIterNext(Tag=tag,
                                                           Maximum=100)
                if (not hasattr(res, 'DatasetMembers') or
                            not res.DatasetMembers):
                    break
                for member in res.DatasetMembers.DatasetMemberInfo:
                    if member.MemberName.endswith(suffix):
                        return member.MemberId
        finally:
            server.DatasetMemberListInfoIterEnd(Tag=tag)

    def _get_lun_details(self, lun_id):
        """Given the ID of a LUN, get the details about that LUN"""
        server = self.client.service
        res = server.LunListInfoIterStart(ObjectNameOrId=lun_id)
        tag = res.Tag
        try:
            res = server.LunListInfoIterNext(Tag=tag, Maximum=1)
            if hasattr(res, 'Luns') and res.Luns.LunInfo:
                return res.Luns.LunInfo[0]
        finally:
            server.LunListInfoIterEnd(Tag=tag)

    def _get_host_details(self, host_id):
        """
        Given the ID of a host (storage system), get the details about that
        host.
        """
        server = self.client.service
        res = server.HostListInfoIterStart(ObjectNameOrId=host_id)
        tag = res.Tag
        try:
            res = server.HostListInfoIterNext(Tag=tag, Maximum=1)
            if hasattr(res, 'Hosts') and res.Hosts.HostInfo:
                return res.Hosts.HostInfo[0]
        finally:
            server.HostListInfoIterEnd(Tag=tag)

    def _get_iqn_for_host(self, host_id):
        """Get the iSCSI Target Name for a storage system"""
        request = self.client.factory.create('Request')
        request.Name = 'iscsi-node-get-name'
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        return response.Results['node-name'][0]

    def _api_elem_is_empty(self, elem):
        """
        Helper routine to figure out if a list returned from a proxy API
        is empty. This is necessary because the API proxy produces nasty
        looking XML.
        """
        if not type(elem) is list:
            return True
        if 0 == len(elem):
            return True
        child = elem[0]
        if isinstance(child, text.Text):
            return True
        if type(child) is str:
            return True
        return False

    def _get_target_portal_for_host(self, host_id, host_address):
        """
        Get the iSCSI Target Portal details for a particular IP address
        on a storage system.
        """
        request = self.client.factory.create('Request')
        request.Name = 'iscsi-portal-list-info'
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        portal = {}
        portals = response.Results['iscsi-portal-list-entries']
        if self._api_elem_is_empty(portals):
            return portal
        portal_infos = portals[0]['iscsi-portal-list-entry-info']
        for portal_info in portal_infos:
            portal['address'] = portal_info['ip-address'][0]
            portal['port'] = portal_info['ip-port'][0]
            portal['portal'] = portal_info['tpgroup-tag'][0]
            if host_address == portal['address']:
                break
        return portal

    def _get_export(self, volume):
        """
        Looks up the LUN in DFM based on the volume and project name, then get
        the LUN's ID. We store that value in the database instead of the iSCSI
        details because we will not have the true iSCSI details until masking
        time (when initialize_connection() is called).
        """
        name = volume['name']
        project = volume['project_id']
        lun_id = self._get_lun_id(name, project)
        if not lun_id:
            msg = _("Failed to find LUN ID for volume %s")
            raise exception.Error(msg % name)
        return {'provider_location': lun_id}

    def ensure_export(self, context, volume):
        """
        Driver entry point to get the iSCSI details about an existing volume
        """
        return self._get_export(volume)

    def create_export(self, context, volume):
        """
        Driver entry point to get the iSCSI details about a new volume
        """
        return self._get_export(volume)

    def remove_export(self, context, volume):
        """
        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """
        pass

    def _find_igroup_for_initiator(self, host_id, initiator_name):
        """
        Look for an existing igroup (initiator group) on the storage system
        containing a given iSCSI initiator and return the name of the igroup.
        """
        request = self.client.factory.create('Request')
        request.Name = 'igroup-list-info'
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        igroups = response.Results['initiator-groups']
        if self._api_elem_is_empty(igroups):
            return None
        igroup_infos = igroups[0]['initiator-group-info']
        for igroup_info in igroup_infos:
            if ('iscsi' != igroup_info['initiator-group-type'][0] or
                'linux' != igroup_info['initiator-group-os-type'][0]):
                continue
            igroup_name = igroup_info['initiator-group-name'][0]
            if not igroup_name.startswith('openstack-'):
                continue
            initiators = igroup_info['initiators'][0]['initiator-info']
            for initiator in initiators:
                if initiator_name == initiator['initiator-name'][0]:
                    return igroup_name
        return None

    def _create_igroup(self, host_id, initiator_name):
        """
        Create a new igroup (initiator group) on the storage system to hold
        the given iSCSI initiator. The group will only have 1 member and will
        be named "openstack-${initiator_name}".
        """
        igroup_name = 'openstack-' + initiator_name
        request = self.client.factory.create('Request')
        request.Name = 'igroup-create'
        igroup_create_xml = (
            '<initiator-group-name>%s</initiator-group-name>'
            '<initiator-group-type>iscsi</initiator-group-type>'
            '<os-type>linux</os-type><ostype>linux</ostype>')
        request.Args = text.Raw(igroup_create_xml % igroup_name)
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        request = self.client.factory.create('Request')
        request.Name = 'igroup-add'
        igroup_add_xml = (
            '<initiator-group-name>%s</initiator-group-name>'
            '<initiator>%s</initiator>')
        request.Args = text.Raw(igroup_add_xml % (igroup_name, initiator_name))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        return igroup_name

    def _get_lun_mappping(self, host_id, lunpath, igroup_name):
        """
        Check if a given LUN is already mapped to the given igroup (initiator
        group). If the LUN is mapped, also return the LUN number for the
        mapping.
        """
        request = self.client.factory.create('Request')
        request.Name = 'lun-map-list-info'
        request.Args = text.Raw('<path>%s</path>' % (lunpath))
        response = self.client.service.ApiProxy(Target=host_id,
                                                 Request=request)
        self._check_fail(request, response)
        igroups = response.Results['initiator-groups']
        if self._api_elem_is_empty(igroups):
            return {'mapped': False}
        igroup_infos = igroups[0]['initiator-group-info']
        for igroup_info in igroup_infos:
            if igroup_name == igroup_info['initiator-group-name'][0]:
                return {'mapped': True, 'lun_num': igroup_info['lun-id'][0]}
        return {'mapped': False}

    def _map_initiator(self, host_id, lunpath, igroup_name):
        """
        Map the given LUN to the given igroup (initiator group). Return the LUN
        number that the LUN was mapped to (the filer will choose the lowest
        available number).
        """
        request = self.client.factory.create('Request')
        request.Name = 'lun-map'
        lun_map_xml = ('<initiator-group>%s</initiator-group>'
                       '<path>%s</path>')
        request.Args = text.Raw(lun_map_xml % (igroup_name, lunpath))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        return response.Results['lun-id-assigned'][0]

    def _unmap_initiator(self, host_id, lunpath, igroup_name):
        """Unmap the given LUN from the given igroup (initiator group)."""
        request = self.client.factory.create('Request')
        request.Name = 'lun-unmap'
        lun_unmap_xml = ('<initiator-group>%s</initiator-group>'
                         '<path>%s</path>')
        request.Args = text.Raw(lun_unmap_xml % (igroup_name, lunpath))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)

    def _ensure_initiator_mapped(self, host_id, lunpath, initiator_name):
        """
        Check if a LUN is mapped to a given initiator already and create
        the mapping if it is not. A new igroup will be created if needed.
        Returns the LUN number for the mapping between the LUN and initiator
        in both cases.
        """
        lunpath = '/vol/' + lunpath
        igroup_name = self._find_igroup_for_initiator(host_id, initiator_name)
        if not igroup_name:
            igroup_name = self._create_igroup(host_id, initiator_name)

        mapping = self._get_lun_mappping(host_id, lunpath, igroup_name)
        if mapping['mapped']:
            return mapping['lun_num']
        return self._map_initiator(host_id, lunpath, igroup_name)

    def _ensure_initiator_unmapped(self, host_id, lunpath, initiator_name):
        """
        Check if a LUN is mapped to a given initiator and remove the
        mapping if it is. This does not destroy the igroup.
        """
        lunpath = '/vol/' + lunpath
        igroup_name = self._find_igroup_for_initiator(host_id, initiator_name)
        if not igroup_name:
            return

        mapping = self._get_lun_mappping(host_id, lunpath, igroup_name)
        if mapping['mapped']:
            self._unmap_initiator(host_id, lunpath, igroup_name)

    def initialize_connection(self, volume, connector):
        """
        Do the LUN masking on the storage system so the initiator can access
        the LUN on the target. Also return the iSCSI properties so the
        initiator can find the LUN. This implementation does not call
        _get_iscsi_properties() to get the properties because cannot store the
        LUN number in the database. We only find out what the LUN number will
        be during this method call so we construct the properties dictionary
        ourselves.
        """
        initiator_name = connector['initiator']
        lun_id = volume['provider_location']
        if not lun_id:
            msg = _("No LUN ID for volume %s")
            raise exception.Error(msg % volume['name'])
        lun = self._get_lun_details(lun_id)
        if not lun:
            msg = _('Failed to get LUN details for LUN ID %s')
            raise exception.Error(msg % lun_id)
        lun_num = self._ensure_initiator_mapped(lun.HostId, lun.LunPath,
                                                initiator_name)

        host = self._get_host_details(lun.HostId)
        if not host:
            msg = _('Failed to get host details for host ID %s')
            raise exception.Error(msg % lun.HostId)

        portal = self._get_target_portal_for_host(host.HostId,
                                                  host.HostAddress)
        if not portal:
            msg = _('Failed to get target portal for filer: %s')
            raise exception.Error(msg % host.HostName)

        iqn = self._get_iqn_for_host(host.HostId)
        if not iqn:
            msg = _('Failed to get target IQN for filer: %s')
            raise exception.Error(msg % host.HostName)

        properties = {}
        properties['target_discovered'] = False
        (address, port) = (portal['address'], portal['port'])
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = lun_num
        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector):
        """
        Unmask the LUN on the storage system so the given intiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        lun_id = volume['provider_location']
        if not lun_id:
            msg = _('No LUN ID for volume %s')
            raise exception.Error(msg % (volume['name']))
        lun = self._get_lun_details(lun_id)
        if not lun:
            msg = _('Failed to get LUN details for LUN ID %s')
            raise exception.Error(msg % (lun_id))
        self._ensure_initiator_unmapped(lun.HostId, lun.LunPath,
                                        initiator_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        raise NotImplementedError()

    def delete_snapshot(self, snapshot):
        raise NotImplementedError()

    def check_for_export(self, context, volume_id):
        raise NotImplementedError()
