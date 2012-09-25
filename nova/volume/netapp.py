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

import suds
from suds import client
from suds.sax import text

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.volume import driver
from nova.volume import volume_types

LOG = logging.getLogger(__name__)

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
               help=('Storage service to use for provisioning '
                    '(when volume_type=None)')),
    cfg.StrOpt('netapp_storage_service_prefix',
               default=None,
               help=('Prefix of storage service name to use for '
                    'provisioning (volume_type name will be appended)')),
    cfg.StrOpt('netapp_vfiler',
               default=None,
               help='Vfiler to use for provisioning'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(netapp_opts)


class DfmDataset(object):
    def __init__(self, id, name, project, type):
        self.id = id
        self.name = name
        self.project = project
        self.type = type


class DfmLun(object):
    def __init__(self, dataset, lunpath, id):
        self.dataset = dataset
        self.lunpath = lunpath
        self.id = id


class NetAppISCSIDriver(driver.ISCSIDriver):
    """NetApp iSCSI volume driver."""

    IGROUP_PREFIX = 'openstack-'
    DATASET_PREFIX = 'OpenStack_'
    DATASET_METADATA_PROJECT_KEY = 'OpenStackProject'
    DATASET_METADATA_VOL_TYPE_KEY = 'OpenStackVolType'

    def __init__(self, *args, **kwargs):
        super(NetAppISCSIDriver, self).__init__(*args, **kwargs)
        self.discovered_luns = []
        self.discovered_datasets = []
        self.lun_table = {}

    def _check_fail(self, request, response):
        """Utility routine to handle checking ZAPI failures."""
        if 'failed' == response.Status:
            name = request.Name
            reason = response.Reason
            msg = _('API %(name)s failed: %(reason)s')
            raise exception.VolumeBackendAPIException(data=msg % locals())

    def _create_client(self, **kwargs):
        """Instantiate a web services client.

        This method creates a "suds" client to make web services calls to the
        DFM server. Note that the WSDL file is quite large and may take
        a few seconds to parse.
        """
        wsdl_url = kwargs['wsdl_url']
        LOG.debug(_('Using WSDL: %s') % wsdl_url)
        if kwargs['cache']:
            self.client = client.Client(wsdl_url, username=kwargs['login'],
                                        password=kwargs['password'])
        else:
            self.client = client.Client(wsdl_url, username=kwargs['login'],
                                        password=kwargs['password'],
                                        cache=None)
        soap_url = 'http://%s:%s/apis/soap/v1' % (kwargs['hostname'],
                                                  kwargs['port'])
        LOG.debug(_('Using DFM server: %s') % soap_url)
        self.client.set_options(location=soap_url)

    def _set_storage_service(self, storage_service):
        """Set the storage service to use for provisioning."""
        LOG.debug(_('Using storage service: %s') % storage_service)
        self.storage_service = storage_service

    def _set_storage_service_prefix(self, storage_service_prefix):
        """Set the storage service prefix to use for provisioning."""
        LOG.debug(_('Using storage service prefix: %s') %
                  storage_service_prefix)
        self.storage_service_prefix = storage_service_prefix

    def _set_vfiler(self, vfiler):
        """Set the vfiler to use for provisioning."""
        LOG.debug(_('Using vfiler: %s') % vfiler)
        self.vfiler = vfiler

    def _check_flags(self):
        """Ensure that the flags we care about are set."""
        required_flags = ['netapp_wsdl_url', 'netapp_login', 'netapp_password',
                'netapp_server_hostname', 'netapp_server_port']
        for flag in required_flags:
            if not getattr(FLAGS, flag, None):
                raise exception.InvalidInput(reason=_('%s is not set') % flag)
        if not (FLAGS.netapp_storage_service or
                FLAGS.netapp_storage_service_prefix):
            raise exception.InvalidInput(reason=_('Either '
                'netapp_storage_service or netapp_storage_service_prefix must '
                'be set'))

    def do_setup(self, context):
        """Setup the NetApp Volume driver.

        Called one time by the manager after the driver is loaded.
        Validate the flags we care about and setup the suds (web services)
        client.
        """
        self._check_flags()
        self._create_client(wsdl_url=FLAGS.netapp_wsdl_url,
            login=FLAGS.netapp_login, password=FLAGS.netapp_password,
            hostname=FLAGS.netapp_server_hostname,
            port=FLAGS.netapp_server_port, cache=True)
        self._set_storage_service(FLAGS.netapp_storage_service)
        self._set_storage_service_prefix(FLAGS.netapp_storage_service_prefix)
        self._set_vfiler(FLAGS.netapp_vfiler)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.

        Invoke a web services API to make sure we can talk to the server.
        Also perform the discovery of datasets and LUNs from DFM.
        """
        self.client.service.DfmAbout()
        LOG.debug(_("Connected to DFM server"))
        self._discover_luns()

    def _get_datasets(self):
        """Get the list of datasets from DFM."""
        server = self.client.service
        res = server.DatasetListInfoIterStart(IncludeMetadata=True)
        tag = res.Tag
        datasets = []
        try:
            while True:
                res = server.DatasetListInfoIterNext(Tag=tag, Maximum=100)
                if not res.Datasets:
                    break
                datasets.extend(res.Datasets.DatasetInfo)
        finally:
            server.DatasetListInfoIterEnd(Tag=tag)
        return datasets

    def _discover_dataset_luns(self, dataset, volume):
        """Discover all of the LUNs in a dataset."""
        server = self.client.service
        res = server.DatasetMemberListInfoIterStart(
                DatasetNameOrId=dataset.id,
                IncludeExportsInfo=True,
                IncludeIndirect=True,
                MemberType='lun_path')
        tag = res.Tag
        suffix = None
        if volume:
            suffix = '/' + volume
        try:
            while True:
                res = server.DatasetMemberListInfoIterNext(Tag=tag,
                                                           Maximum=100)
                if (not hasattr(res, 'DatasetMembers') or
                            not res.DatasetMembers):
                    break
                for member in res.DatasetMembers.DatasetMemberInfo:
                    if suffix and not member.MemberName.endswith(suffix):
                        continue
                    # MemberName is the full LUN path in this format:
                    # host:/volume/qtree/lun
                    lun = DfmLun(dataset, member.MemberName, member.MemberId)
                    self.discovered_luns.append(lun)
        finally:
            server.DatasetMemberListInfoIterEnd(Tag=tag)

    def _discover_luns(self):
        """Discover the LUNs from DFM.

        Discover all of the OpenStack-created datasets and LUNs in the DFM
        database.
        """
        datasets = self._get_datasets()
        self.discovered_datasets = []
        self.discovered_luns = []
        for dataset in datasets:
            if not dataset.DatasetName.startswith(self.DATASET_PREFIX):
                continue
            if (not hasattr(dataset, 'DatasetMetadata') or
                    not dataset.DatasetMetadata):
                continue
            project = None
            type = None
            for field in dataset.DatasetMetadata.DfmMetadataField:
                if field.FieldName == self.DATASET_METADATA_PROJECT_KEY:
                    project = field.FieldValue
                elif field.FieldName == self.DATASET_METADATA_VOL_TYPE_KEY:
                    type = field.FieldValue
            if not project:
                continue
            ds = DfmDataset(dataset.DatasetId, dataset.DatasetName,
                            project, type)
            self.discovered_datasets.append(ds)
            self._discover_dataset_luns(ds, None)
        dataset_count = len(self.discovered_datasets)
        lun_count = len(self.discovered_luns)
        msg = _("Discovered %(dataset_count)s datasets and %(lun_count)s LUNs")
        LOG.debug(msg % locals())
        self.lun_table = {}

    def _get_job_progress(self, job_id):
        """Get progress of one running DFM job.

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
        """Wait until a job terminates.

        Poll the job until it completes or an error is detected. Return the
        final list of progress events if it completes successfully.
        """
        while True:
            events = self._get_job_progress(job_id)
            for event in events:
                if event.EventStatus == 'error':
                    msg = _('Job failed: %s') % (event.ErrorMessage)
                    raise exception.VolumeBackendAPIException(data=msg)
                if event.EventType == 'job-end':
                    return events
            time.sleep(5)

    def _dataset_name(self, project, ss_type):
        """Return the dataset name for a given project and volume type."""
        _project = project.replace(' ', '_').replace('-', '_')
        dataset_name = self.DATASET_PREFIX + _project
        if not ss_type:
            return dataset_name
        _type = ss_type.replace(' ', '_').replace('-', '_')
        return dataset_name + '_' + _type

    def _get_dataset(self, dataset_name):
        """Lookup a dataset by name in the list of discovered datasets."""
        for dataset in self.discovered_datasets:
            if dataset.name == dataset_name:
                return dataset
        return None

    def _create_dataset(self, dataset_name, project, ss_type):
        """Create a new dataset using the storage service.

        The export settings are set to create iSCSI LUNs aligned for Linux.
        Returns the ID of the new dataset.
        """
        if ss_type and not self.storage_service_prefix:
            msg = _('Attempt to use volume_type without specifying '
                'netapp_storage_service_prefix flag.')
            raise exception.VolumeBackendAPIException(data=msg)
        if not (ss_type or self.storage_service):
            msg = _('You must set the netapp_storage_service flag in order to '
                'create volumes with no volume_type.')
            raise exception.VolumeBackendAPIException(data=msg)
        storage_service = self.storage_service
        if ss_type:
            storage_service = self.storage_service_prefix + ss_type

        factory = self.client.factory

        lunmap = factory.create('DatasetLunMappingInfo')
        lunmap.IgroupOsType = 'linux'
        export = factory.create('DatasetExportInfo')
        export.DatasetExportProtocol = 'iscsi'
        export.DatasetLunMappingInfo = lunmap
        detail = factory.create('StorageSetInfo')
        detail.DpNodeName = 'Primary data'
        detail.DatasetExportInfo = export
        if hasattr(self, 'vfiler') and self.vfiler:
            detail.ServerNameOrId = self.vfiler
        details = factory.create('ArrayOfStorageSetInfo')
        details.StorageSetInfo = [detail]
        field1 = factory.create('DfmMetadataField')
        field1.FieldName = self.DATASET_METADATA_PROJECT_KEY
        field1.FieldValue = project
        field2 = factory.create('DfmMetadataField')
        field2.FieldName = self.DATASET_METADATA_VOL_TYPE_KEY
        field2.FieldValue = ss_type
        metadata = factory.create('ArrayOfDfmMetadataField')
        metadata.DfmMetadataField = [field1, field2]

        res = self.client.service.StorageServiceDatasetProvision(
                StorageServiceNameOrId=storage_service,
                DatasetName=dataset_name,
                AssumeConfirmation=True,
                StorageSetDetails=details,
                DatasetMetadata=metadata)

        ds = DfmDataset(res.DatasetId, dataset_name, project, ss_type)
        self.discovered_datasets.append(ds)
        return ds

    def _provision(self, name, description, project, ss_type, size):
        """Provision a LUN through provisioning manager.

        The LUN will be created inside a dataset associated with the project.
        If the dataset doesn't already exist, we create it using the storage
        service specified in the nova conf.
        """
        dataset_name = self._dataset_name(project, ss_type)
        dataset = self._get_dataset(dataset_name)
        if not dataset:
            dataset = self._create_dataset(dataset_name, project, ss_type)

        info = self.client.factory.create('ProvisionMemberRequestInfo')
        info.Name = name
        if description:
            info.Description = description
        info.Size = size
        info.MaximumSnapshotSpace = 2 * long(size)

        server = self.client.service
        lock_id = server.DatasetEditBegin(DatasetNameOrId=dataset.id)
        try:
            server.DatasetProvisionMember(EditLockId=lock_id,
                                          ProvisionMemberRequestInfo=info)
            res = server.DatasetEditCommit(EditLockId=lock_id,
                                           AssumeConfirmation=True)
        except (suds.WebFault, Exception):
            server.DatasetEditRollback(EditLockId=lock_id)
            msg = _('Failed to provision dataset member')
            raise exception.VolumeBackendAPIException(data=msg)

        lun_id = None
        lunpath = None

        for info in res.JobIds.JobInfo:
            events = self._wait_for_job(info.JobId)
            for event in events:
                if event.EventType != 'lun-create':
                    continue
                lunpath = event.ProgressLunInfo.LunName
                lun_id = event.ProgressLunInfo.LunPathId

        if not lun_id:
            msg = _('No LUN was created by the provision job')
            raise exception.VolumeBackendAPIException(data=msg)

        lun = DfmLun(dataset, lunpath, lun_id)
        self.discovered_luns.append(lun)
        self.lun_table[name] = lun

    def _get_ss_type(self, volume):
        """Get the storage service type for a volume."""
        id = volume['volume_type_id']
        if not id:
            return None
        volume_type = volume_types.get_volume_type(None, id)
        if not volume_type:
            return None
        return volume_type['name']

    def _remove_destroy(self, name, project):
        """Remove the LUN from the dataset, also destroying it.

        Remove the LUN from the dataset and destroy the actual LUN on the
        storage system.
        """
        lun = self._lookup_lun_for_volume(name, project)
        member = self.client.factory.create('DatasetMemberParameter')
        member.ObjectNameOrId = lun.id
        members = self.client.factory.create('ArrayOfDatasetMemberParameter')
        members.DatasetMemberParameter = [member]

        server = self.client.service
        lock_id = server.DatasetEditBegin(DatasetNameOrId=lun.dataset.id)
        try:
            server.DatasetRemoveMember(EditLockId=lock_id, Destroy=True,
                                       DatasetMemberParameters=members)
            server.DatasetEditCommit(EditLockId=lock_id,
                                     AssumeConfirmation=True)
        except (suds.WebFault, Exception):
            server.DatasetEditRollback(EditLockId=lock_id)
            msg = _('Failed to remove and delete dataset member')
            raise exception.VolumeBackendAPIException(data=msg)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        default_size = '104857600'  # 100 MB
        gigabytes = 1073741824L  # 2^30
        name = volume['name']
        project = volume['project_id']
        display_name = volume['display_name']
        display_description = volume['display_description']
        description = None
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
        ss_type = self._get_ss_type(volume)
        self._provision(name, description, project, ss_type, size)

    def _lookup_lun_for_volume(self, name, project):
        """Lookup the LUN that corresponds to the give volume.

        Initial lookups involve a table scan of all of the discovered LUNs,
        but later lookups are done instantly from the hashtable.
        """
        if name in self.lun_table:
            return self.lun_table[name]
        lunpath_suffix = '/' + name
        for lun in self.discovered_luns:
            if lun.dataset.project != project:
                continue
            if lun.lunpath.endswith(lunpath_suffix):
                self.lun_table[name] = lun
                return lun
        msg = _("No entry in LUN table for volume %s") % (name)
        raise exception.VolumeBackendAPIException(data=msg)

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        name = volume['name']
        project = volume['project_id']
        self._remove_destroy(name, project)

    def _get_lun_details(self, lun_id):
        """Given the ID of a LUN, get the details about that LUN."""
        server = self.client.service
        res = server.LunListInfoIterStart(ObjectNameOrId=lun_id)
        tag = res.Tag
        try:
            res = server.LunListInfoIterNext(Tag=tag, Maximum=1)
            if hasattr(res, 'Luns') and res.Luns.LunInfo:
                return res.Luns.LunInfo[0]
        finally:
            server.LunListInfoIterEnd(Tag=tag)
        msg = _('Failed to get LUN details for LUN ID %s')
        raise exception.VolumeBackendAPIException(data=msg % lun_id)

    def _get_host_details(self, host_id):
        """Given the ID of a host, get the details about it.

        A "host" is a storage system here.
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
        msg = _('Failed to get host details for host ID %s')
        raise exception.VolumeBackendAPIException(data=msg % host_id)

    def _get_iqn_for_host(self, host_id):
        """Get the iSCSI Target Name for a storage system."""
        request = self.client.factory.create('Request')
        request.Name = 'iscsi-node-get-name'
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        return response.Results['node-name'][0]

    def _api_elem_is_empty(self, elem):
        """Return true if the API element should be considered empty.

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
        """Get iSCSI target portal for a storage system.

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
        """Get the iSCSI export details for a volume.

        Looks up the LUN in DFM based on the volume and project name, then get
        the LUN's ID. We store that value in the database instead of the iSCSI
        details because we will not have the true iSCSI details until masking
        time (when initialize_connection() is called).
        """
        name = volume['name']
        project = volume['project_id']
        lun = self._lookup_lun_for_volume(name, project)
        return {'provider_location': lun.id}

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        return self._get_export(volume)

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        return self._get_export(volume)

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume.

        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """
        pass

    def _find_igroup_for_initiator(self, host_id, initiator_name):
        """Get the igroup for an initiator.

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
            if not igroup_name.startswith(self.IGROUP_PREFIX):
                continue
            initiators = igroup_info['initiators'][0]['initiator-info']
            for initiator in initiators:
                if initiator_name == initiator['initiator-name'][0]:
                    return igroup_name
        return None

    def _create_igroup(self, host_id, initiator_name):
        """Create a new igroup.

        Create a new igroup (initiator group) on the storage system to hold
        the given iSCSI initiator. The group will only have 1 member and will
        be named "openstack-${initiator_name}".
        """
        igroup_name = self.IGROUP_PREFIX + initiator_name
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
        """Get the mapping between a LUN and an igroup.

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
        """Map a LUN to an igroup.

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
        """Ensure that a LUN is mapped to a particular initiator.

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
        """Ensure that a LUN is not mapped to a particular initiator.

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
        """Driver entry point to attach a volume to an instance.

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
            msg = _("No LUN ID for volume %s") % volume['name']
            raise exception.VolumeBackendAPIException(data=msg)
        lun = self._get_lun_details(lun_id)
        lun_num = self._ensure_initiator_mapped(lun.HostId, lun.LunPath,
                                                initiator_name)
        host = self._get_host_details(lun.HostId)
        portal = self._get_target_portal_for_host(host.HostId,
                                                  host.HostAddress)
        if not portal:
            msg = _('Failed to get target portal for filer: %s')
            raise exception.VolumeBackendAPIException(data=msg % host.HostName)

        iqn = self._get_iqn_for_host(host.HostId)
        if not iqn:
            msg = _('Failed to get target IQN for filer: %s')
            raise exception.VolumeBackendAPIException(data=msg % host.HostName)

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
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given intiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        lun_id = volume['provider_location']
        if not lun_id:
            msg = _('No LUN ID for volume %s') % volume['name']
            raise exception.VolumeBackendAPIException(data=msg)
        lun = self._get_lun_details(lun_id)
        self._ensure_initiator_unmapped(lun.HostId, lun.LunPath,
                                        initiator_name)

    def _is_clone_done(self, host_id, clone_op_id, volume_uuid):
        """Check the status of a clone operation.

        Return True if done, False otherwise.
        """
        request = self.client.factory.create('Request')
        request.Name = 'clone-list-status'
        clone_list_status_xml = (
            '<clone-id><clone-id-info>'
            '<clone-op-id>%s</clone-op-id>'
            '<volume-uuid>%s</volume-uuid>'
            '</clone-id-info></clone-id>')
        request.Args = text.Raw(clone_list_status_xml % (clone_op_id,
                                                          volume_uuid))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        status = response.Results['status']
        if self._api_elem_is_empty(status):
            return False
        ops_info = status[0]['ops-info'][0]
        state = ops_info['clone-state'][0]
        return 'completed' == state

    def _clone_lun(self, host_id, src_path, dest_path, snap):
        """Create a clone of a NetApp LUN.

        The clone initially consumes no space and is not space reserved.
        """
        request = self.client.factory.create('Request')
        request.Name = 'clone-start'
        clone_start_xml = (
            '<source-path>%s</source-path><no-snap>%s</no-snap>'
            '<destination-path>%s</destination-path>')
        if snap:
            no_snap = 'false'
        else:
            no_snap = 'true'
        request.Args = text.Raw(clone_start_xml % (src_path, no_snap,
                                                    dest_path))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        clone_id = response.Results['clone-id'][0]
        clone_id_info = clone_id['clone-id-info'][0]
        clone_op_id = clone_id_info['clone-op-id'][0]
        volume_uuid = clone_id_info['volume-uuid'][0]
        while not self._is_clone_done(host_id, clone_op_id, volume_uuid):
            time.sleep(5)

    def _refresh_dfm_luns(self, host_id):
        """Refresh the LUN list for one filer in DFM."""
        server = self.client.service
        server.DfmObjectRefresh(ObjectNameOrId=host_id, ChildType='lun_path')
        while True:
            time.sleep(15)
            res = server.DfmMonitorTimestampList(HostNameOrId=host_id)
            for timestamp in res.DfmMonitoringTimestamp:
                if 'lun' != timestamp.MonitorName:
                    continue
                if timestamp.LastMonitoringTimestamp:
                    return

    def _destroy_lun(self, host_id, lun_path):
        """Destroy a LUN on the filer."""
        request = self.client.factory.create('Request')
        request.Name = 'lun-offline'
        path_xml = '<path>%s</path>'
        request.Args = text.Raw(path_xml % lun_path)
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)
        request = self.client.factory.create('Request')
        request.Name = 'lun-destroy'
        request.Args = text.Raw(path_xml % lun_path)
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)

    def _resize_volume(self, host_id, vol_name, new_size):
        """Resize the volume by the amount requested."""
        request = self.client.factory.create('Request')
        request.Name = 'volume-size'
        volume_size_xml = (
            '<volume>%s</volume><new-size>%s</new-size>')
        request.Args = text.Raw(volume_size_xml % (vol_name, new_size))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)

    def _create_qtree(self, host_id, vol_name, qtree_name):
        """Create a qtree the filer."""
        request = self.client.factory.create('Request')
        request.Name = 'qtree-create'
        qtree_create_xml = (
            '<mode>0755</mode><volume>%s</volume><qtree>%s</qtree>')
        request.Args = text.Raw(qtree_create_xml % (vol_name, qtree_name))
        response = self.client.service.ApiProxy(Target=host_id,
                                                Request=request)
        self._check_fail(request, response)

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.

        This driver implements snapshots by using efficient single-file
        (LUN) cloning.
        """
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        project = snapshot['project_id']
        lun = self._lookup_lun_for_volume(vol_name, project)
        lun_id = lun.id
        lun = self._get_lun_details(lun_id)
        extra_gb = snapshot['volume_size']
        new_size = '+%dg' % extra_gb
        self._resize_volume(lun.HostId, lun.VolumeName, new_size)
        # LunPath is the partial LUN path in this format: volume/qtree/lun
        lun_path = str(lun.LunPath)
        lun_name = lun_path[lun_path.rfind('/') + 1:]
        qtree_path = '/vol/%s/%s' % (lun.VolumeName, lun.QtreeName)
        src_path = '%s/%s' % (qtree_path, lun_name)
        dest_path = '%s/%s' % (qtree_path, snapshot_name)
        self._clone_lun(lun.HostId, src_path, dest_path, True)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        project = snapshot['project_id']
        lun = self._lookup_lun_for_volume(vol_name, project)
        lun_id = lun.id
        lun = self._get_lun_details(lun_id)
        lun_path = '/vol/%s/%s/%s' % (lun.VolumeName, lun.QtreeName,
                                      snapshot_name)
        self._destroy_lun(lun.HostId, lun_path)
        extra_gb = snapshot['volume_size']
        new_size = '-%dg' % extra_gb
        self._resize_volume(lun.HostId, lun.VolumeName, new_size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for creating a new volume from a snapshot.

        Many would call this "cloning" and in fact we use cloning to implement
        this feature.
        """
        vol_size = volume['size']
        snap_size = snapshot['volume_size']
        if vol_size != snap_size:
            msg = _('Cannot create volume of size %(vol_size)s from '
                'snapshot of size %(snap_size)s')
            raise exception.VolumeBackendAPIException(data=msg % locals())
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        project = snapshot['project_id']
        lun = self._lookup_lun_for_volume(vol_name, project)
        lun_id = lun.id
        dataset = lun.dataset
        old_type = dataset.type
        new_type = self._get_ss_type(volume)
        if new_type != old_type:
            msg = _('Cannot create volume of type %(new_type)s from '
                'snapshot of type %(old_type)s')
            raise exception.VolumeBackendAPIException(data=msg % locals())
        lun = self._get_lun_details(lun_id)
        extra_gb = vol_size
        new_size = '+%dg' % extra_gb
        self._resize_volume(lun.HostId, lun.VolumeName, new_size)
        clone_name = volume['name']
        self._create_qtree(lun.HostId, lun.VolumeName, clone_name)
        src_path = '/vol/%s/%s/%s' % (lun.VolumeName, lun.QtreeName,
                                      snapshot_name)
        dest_path = '/vol/%s/%s/%s' % (lun.VolumeName, clone_name, clone_name)
        self._clone_lun(lun.HostId, src_path, dest_path, False)
        self._refresh_dfm_luns(lun.HostId)
        self._discover_dataset_luns(dataset, clone_name)

    def check_for_export(self, context, volume_id):
        raise NotImplementedError()


class NetAppLun(object):
    """Represents a LUN on NetApp storage."""

    def __init__(self, handle, name, size, metadata_dict):
        self.handle = handle
        self.name = name
        self.size = size
        self.metadata = metadata_dict

    def get_metadata_property(self, prop):
        """Get the metadata property of a LUN."""
        if prop in self.metadata:
            return self.metadata[prop]
        name = self.name
        msg = _("No metadata property %(prop)s defined for the LUN %(name)s")
        LOG.debug(msg % locals())


class NetAppCmodeISCSIDriver(driver.ISCSIDriver):
    """NetApp C-mode iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(NetAppCmodeISCSIDriver, self).__init__(*args, **kwargs)
        self.lun_table = {}

    def _create_client(self, **kwargs):
        """Instantiate a web services client.

        This method creates a "suds" client to make web services calls to the
        DFM server. Note that the WSDL file is quite large and may take
        a few seconds to parse.
        """
        wsdl_url = kwargs['wsdl_url']
        LOG.debug(_('Using WSDL: %s') % wsdl_url)
        if kwargs['cache']:
            self.client = client.Client(wsdl_url, username=kwargs['login'],
                                        password=kwargs['password'])
        else:
            self.client = client.Client(wsdl_url, username=kwargs['login'],
                                        password=kwargs['password'],
                                        cache=None)

    def _check_flags(self):
        """Ensure that the flags we care about are set."""
        required_flags = ['netapp_wsdl_url', 'netapp_login', 'netapp_password',
                'netapp_server_hostname', 'netapp_server_port']
        for flag in required_flags:
            if not getattr(FLAGS, flag, None):
                msg = _('%s is not set') % flag
                raise exception.InvalidInput(data=msg)

    def do_setup(self, context):
        """Setup the NetApp Volume driver.

        Called one time by the manager after the driver is loaded.
        Validate the flags we care about and setup the suds (web services)
        client.
        """
        self._check_flags()
        self._create_client(wsdl_url=FLAGS.netapp_wsdl_url,
            login=FLAGS.netapp_login, password=FLAGS.netapp_password,
            hostname=FLAGS.netapp_server_hostname,
            port=FLAGS.netapp_server_port, cache=True)

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate.

        Discovers the LUNs on the NetApp server.
        """
        self.lun_table = {}
        luns = self.client.service.ListLuns()
        for lun in luns:
            meta_dict = {}
            if hasattr(lun, 'Metadata'):
                meta_dict = self._create_dict_from_meta(lun.Metadata)
            discovered_lun = NetAppLun(lun.Handle, lun.Name, lun.Size,
                meta_dict)
            self._add_lun_to_table(discovered_lun)
        LOG.debug(_("Success getting LUN list from server"))

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        default_size = '104857600'  # 100 MB
        gigabytes = 1073741824L  # 2^30
        name = volume['name']
        if int(volume['size']) == 0:
            size = default_size
        else:
            size = str(int(volume['size']) * gigabytes)
        extra_args = {}
        extra_args['OsType'] = 'linux'
        extra_args['QosType'] = self._get_qos_type(volume)
        extra_args['Container'] = volume['project_id']
        extra_args['Display'] = volume['display_name']
        extra_args['Description'] = volume['display_description']
        extra_args['SpaceReserved'] = True
        server = self.client.service
        metadata = self._create_metadata_list(extra_args)
        lun = server.ProvisionLun(Name=name, Size=size,
                                  Metadata=metadata)
        LOG.debug(_("Created LUN with name %s") % name)
        self._add_lun_to_table(NetAppLun(lun.Handle, lun.Name,
             lun.Size, self._create_dict_from_meta(lun.Metadata)))

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        name = volume['name']
        handle = self._get_lun_handle(name)
        self.client.service.DestroyLun(Handle=handle)
        LOG.debug(_("Destroyed LUN %s") % handle)
        self.lun_table.pop(name)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        handle = self._get_lun_handle(volume['name'])
        return {'provider_location': handle}

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        handle = self._get_lun_handle(volume['name'])
        return {'provider_location': handle}

    def remove_export(self, context, volume):
        """Driver exntry point to remove an export for a volume.

        Since exporting is idempotent in this driver, we have nothing
        to do for unexporting.
        """
        pass

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance.

        Do the LUN masking on the storage system so the initiator can access
        the LUN on the target. Also return the iSCSI properties so the
        initiator can find the LUN. This implementation does not call
        _get_iscsi_properties() to get the properties because cannot store the
        LUN number in the database. We only find out what the LUN number will
        be during this method call so we construct the properties dictionary
        ourselves.
        """
        initiator_name = connector['initiator']
        handle = volume['provider_location']
        server = self.client.service
        server.MapLun(Handle=handle, InitiatorType="iscsi",
                      InitiatorName=initiator_name)
        msg = _("Mapped LUN %(handle)s to the initiator %(initiator_name)s")
        LOG.debug(msg % locals())

        target_details_list = server.GetLunTargetDetails(Handle=handle,
                InitiatorType="iscsi", InitiatorName=initiator_name)
        msg = _("Succesfully fetched target details for LUN %(handle)s and "
                "initiator %(initiator_name)s")
        LOG.debug(msg % locals())

        if not target_details_list:
            msg = _('Failed to get LUN target details for the LUN %s')
            raise exception.VolumeBackendAPIException(msg % handle)
        target_details = target_details_list[0]
        if not target_details.Address and target_details.Port:
            msg = _('Failed to get target portal for the LUN %s')
            raise exception.VolumeBackendAPIException(msg % handle)
        iqn = target_details.Iqn
        if not iqn:
            msg = _('Failed to get target IQN for the LUN %s')
            raise exception.VolumeBackendAPIException(msg % handle)

        properties = {}
        properties['target_discovered'] = False
        (address, port) = (target_details.Address, target_details.Port)
        properties['target_portal'] = '%s:%s' % (address, port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = target_details.LunNumber
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
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given intiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        handle = volume['provider_location']
        self.client.service.UnmapLun(Handle=handle, InitiatorType="iscsi",
                                     InitiatorName=initiator_name)
        msg = _("Unmapped LUN %(handle)s from the initiator "
                "%(initiator_name)s")
        LOG.debug(msg % locals())

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot.

        This driver implements snapshots by using efficient single-file
        (LUN) cloning.
        """
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']
        lun = self.lun_table[vol_name]
        extra_args = {'SpaceReserved': False}
        self._clone_lun(lun.handle, snapshot_name, extra_args)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        handle = self._get_lun_handle(snapshot['name'])
        self.client.service.DestroyLun(Handle=handle)
        LOG.debug(_("Destroyed LUN %s") % handle)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for creating a new volume from a snapshot.

        Many would call this "cloning" and in fact we use cloning to implement
        this feature.
        """
        snapshot_name = snapshot['name']
        lun = self.lun_table[snapshot_name]
        new_name = volume['name']
        extra_args = {}
        extra_args['OsType'] = 'linux'
        extra_args['QosType'] = self._get_qos_type(volume)
        extra_args['Container'] = volume['project_id']
        extra_args['Display'] = volume['display_name']
        extra_args['Description'] = volume['display_description']
        extra_args['SpaceReserved'] = True
        self._clone_lun(lun.handle, new_name, extra_args)

    def check_for_export(self, context, volume_id):
        raise NotImplementedError()

    def _get_qos_type(self, volume):
        """Get the storage service type for a volume."""
        type_id = volume['volume_type_id']
        if not type_id:
            return None
        volume_type = volume_types.get_volume_type(None, type_id)
        if not volume_type:
            return None
        return volume_type['name']

    def _add_lun_to_table(self, lun):
        """Adds LUN to cache table."""
        if not isinstance(lun, NetAppLun):
            msg = _("Object is not a NetApp LUN.")
            raise exception.VolumeBackendAPIException(data=msg)
        self.lun_table[lun.name] = lun

    def _clone_lun(self, handle, new_name, extra_args):
        """Clone LUN with the given handle to the new name."""
        server = self.client.service
        metadata = self._create_metadata_list(extra_args)
        lun = server.CloneLun(Handle=handle, NewName=new_name,
                              Metadata=metadata)
        LOG.debug(_("Cloned LUN with new name %s") % new_name)
        self._add_lun_to_table(NetAppLun(lun.Handle, lun.Name,
             lun.Size, self._create_dict_from_meta(lun.Metadata)))

    def _create_metadata_list(self, extra_args):
        """Creates metadata from kwargs."""
        metadata = []
        for key in extra_args.keys():
            meta = self.client.factory.create("Metadata")
            meta.Key = key
            meta.Value = extra_args[key]
            metadata.append(meta)
        return metadata

    def _get_lun_handle(self, name):
        """Get the details for a LUN from our cache table."""
        if not name in self.lun_table:
            LOG.warn(_("Could not find handle for LUN named %s") % name)
            return None
        return self.lun_table[name].handle

    def _create_dict_from_meta(self, metadata):
        """Creates dictionary from metadata array."""
        meta_dict = {}
        if not metadata:
            return meta_dict
        for meta in metadata:
            meta_dict[meta.Key] = meta.Value
        return meta_dict
