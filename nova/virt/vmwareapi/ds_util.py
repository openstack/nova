# Copyright (c) 2014 VMware, Inc.
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
Datastore utility functions
"""
import collections

from oslo_log import log as logging
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import pbm
from oslo_vmware import vim_util as vutil

from nova import exception
from nova.i18n import _
from nova.virt.vmwareapi import constants
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)
ALL_SUPPORTED_DS_TYPES = frozenset([constants.DATASTORE_TYPE_VMFS,
                                    constants.DATASTORE_TYPE_NFS,
                                    constants.DATASTORE_TYPE_NFS41,
                                    constants.DATASTORE_TYPE_VSAN])


DcInfo = collections.namedtuple('DcInfo',
                                ['ref', 'name', 'vmFolder'])

# A cache for datastore/datacenter mappings. The key will be
# the datastore moref. The value will be the DcInfo object.
_DS_DC_MAPPING = {}


def _select_datastore(session, data_stores, best_match, datastore_regex=None,
                      storage_policy=None,
                      allowed_ds_types=ALL_SUPPORTED_DS_TYPES):
    """Find the most preferable datastore in a given RetrieveResult object.

    :param session: vmwareapi session
    :param data_stores: a RetrieveResult object from vSphere API call
    :param best_match: the current best match for datastore
    :param datastore_regex: an optional regular expression to match names
    :param storage_policy: storage policy for the datastore
    :param allowed_ds_types: a list of acceptable datastore type names
    :return: datastore_ref, datastore_name, capacity, freespace
    """

    if storage_policy:
        matching_ds = _filter_datastores_matching_storage_policy(
            session, data_stores, storage_policy)
        if not matching_ds:
            return best_match
    else:
        matching_ds = data_stores

    # data_stores is actually a RetrieveResult object from vSphere API call
    for obj_content in matching_ds.objects:
        # the propset attribute "need not be set" by returning API
        if not hasattr(obj_content, 'propSet'):
            continue

        propdict = vm_util.propset_dict(obj_content.propSet)
        if _is_datastore_valid(propdict, datastore_regex, allowed_ds_types):
            new_ds = ds_obj.Datastore(
                    ref=obj_content.obj,
                    name=propdict['summary.name'],
                    capacity=propdict['summary.capacity'],
                    freespace=propdict['summary.freeSpace'])
            # favor datastores with more free space
            if (best_match is None or
                new_ds.freespace > best_match.freespace):
                best_match = new_ds

    return best_match


def _is_datastore_valid(propdict, datastore_regex, ds_types):
    """Checks if a datastore is valid based on the following criteria.

       Criteria:
       - Datastore is accessible
       - Datastore is not in maintenance mode (optional)
       - Datastore's type is one of the given ds_types
       - Datastore matches the supplied regex (optional)

       :param propdict: datastore summary dict
       :param datastore_regex : Regex to match the name of a datastore.
    """

    # Local storage identifier vSphere doesn't support CIFS or
    # vfat for datastores, therefore filtered
    return (propdict.get('summary.accessible') and
            (propdict.get('summary.maintenanceMode') is None or
             propdict.get('summary.maintenanceMode') == 'normal') and
            propdict['summary.type'] in ds_types and
            (datastore_regex is None or
             datastore_regex.match(propdict['summary.name'])))


def get_datastore(session, cluster, datastore_regex=None,
                  storage_policy=None,
                  allowed_ds_types=ALL_SUPPORTED_DS_TYPES):
    """Get the datastore list and choose the most preferable one."""
    datastore_ret = session._call_method(vutil,
                                         "get_object_property",
                                         cluster,
                                         "datastore")
    # If there are no datastores in the cluster then an exception is
    # raised
    if not datastore_ret:
        raise exception.DatastoreNotFound()

    data_store_mors = datastore_ret.ManagedObjectReference
    data_stores = session._call_method(vim_util,
                            "get_properties_for_a_collection_of_objects",
                            "Datastore", data_store_mors,
                            ["summary.type", "summary.name",
                             "summary.capacity", "summary.freeSpace",
                             "summary.accessible",
                             "summary.maintenanceMode"])

    best_match = None
    while data_stores:
        best_match = _select_datastore(session,
                                       data_stores,
                                       best_match,
                                       datastore_regex,
                                       storage_policy,
                                       allowed_ds_types)
        data_stores = session._call_method(vutil, 'continue_retrieval',
                                           data_stores)
    if best_match:
        return best_match

    if storage_policy:
        raise exception.DatastoreNotFound(
            _("Storage policy %s did not match any datastores")
            % storage_policy)
    elif datastore_regex:
        raise exception.DatastoreNotFound(
            _("Datastore regex %s did not match any datastores")
            % datastore_regex.pattern)
    else:
        raise exception.DatastoreNotFound()


def _get_allowed_datastores(data_stores, datastore_regex):
    allowed = []
    for obj_content in data_stores.objects:
        # the propset attribute "need not be set" by returning API
        if not hasattr(obj_content, 'propSet'):
            continue

        propdict = vm_util.propset_dict(obj_content.propSet)
        if _is_datastore_valid(propdict,
                               datastore_regex,
                               ALL_SUPPORTED_DS_TYPES):
            allowed.append(ds_obj.Datastore(ref=obj_content.obj,
                                    name=propdict['summary.name'],
                                    capacity=propdict['summary.capacity'],
                                    freespace=propdict['summary.freeSpace']))

    return allowed


def get_available_datastores(session, cluster=None, datastore_regex=None):
    """Get the datastore list and choose the first local storage."""
    ds = session._call_method(vutil,
                              "get_object_property",
                              cluster,
                              "datastore")
    if not ds:
        return []
    data_store_mors = ds.ManagedObjectReference
    # NOTE(garyk): use utility method to retrieve remote objects
    data_stores = session._call_method(vim_util,
            "get_properties_for_a_collection_of_objects",
            "Datastore", data_store_mors,
            ["summary.type", "summary.name", "summary.accessible",
             "summary.maintenanceMode", "summary.capacity",
             "summary.freeSpace"])

    allowed = []
    while data_stores:
        allowed.extend(_get_allowed_datastores(data_stores, datastore_regex))
        data_stores = session._call_method(vutil, 'continue_retrieval',
                                           data_stores)
    return allowed


def get_allowed_datastore_types(disk_type):
    if disk_type == constants.DISK_TYPE_STREAM_OPTIMIZED:
        return ALL_SUPPORTED_DS_TYPES
    return ALL_SUPPORTED_DS_TYPES - frozenset([constants.DATASTORE_TYPE_VSAN])


def get_datacenter_ref(session, dc_path):
    return session._call_method(
        session.vim,
        "FindByInventoryPath",
        session.vim.service_content.searchIndex,
        inventoryPath=dc_path)


def file_delete(session, ds_path, dc_ref):
    LOG.debug("Deleting the datastore file %s", ds_path)
    vim = session.vim
    file_delete_task = session._call_method(
            vim,
            "DeleteDatastoreFile_Task",
            vim.service_content.fileManager,
            name=str(ds_path),
            datacenter=dc_ref)
    session._wait_for_task(file_delete_task)
    LOG.debug("Deleted the datastore file")


def file_copy(session, src_file, src_dc_ref, dst_file, dst_dc_ref):
    LOG.debug("Copying the datastore file from %(src)s to %(dst)s",
              {'src': src_file, 'dst': dst_file})
    vim = session.vim
    copy_task = session._call_method(
            vim,
            "CopyDatastoreFile_Task",
            vim.service_content.fileManager,
            sourceName=src_file,
            sourceDatacenter=src_dc_ref,
            destinationName=dst_file,
            destinationDatacenter=dst_dc_ref)
    session._wait_for_task(copy_task)
    LOG.debug("Copied the datastore file")


def disk_move(session, dc_ref, src_file, dst_file):
    """Moves the source virtual disk to the destination.

    The list of possible faults that the server can return on error
    include:

    * CannotAccessFile: Thrown if the source file or folder cannot be
      moved because of insufficient permissions.
    * FileAlreadyExists: Thrown if a file with the given name already
      exists at the destination.
    * FileFault: Thrown if there is a generic file error
    * FileLocked: Thrown if the source file or folder is currently
      locked or in use.
    * FileNotFound: Thrown if the file or folder specified by sourceName
      is not found.
    * InvalidDatastore: Thrown if the operation cannot be performed on
      the source or destination datastores.
    * NoDiskSpace: Thrown if there is not enough space available on the
      destination datastore.
    * RuntimeFault: Thrown if any type of runtime fault is thrown that
      is not covered by the other faults; for example,
      a communication error.

    """
    LOG.debug("Moving virtual disk from %(src)s to %(dst)s.",
              {'src': src_file, 'dst': dst_file})
    move_task = session._call_method(
            session.vim,
            "MoveVirtualDisk_Task",
            session.vim.service_content.virtualDiskManager,
            sourceName=str(src_file),
            sourceDatacenter=dc_ref,
            destName=str(dst_file),
            destDatacenter=dc_ref,
            force=False)
    session._wait_for_task(move_task)
    LOG.info("Moved virtual disk from %(src)s to %(dst)s.",
             {'src': src_file, 'dst': dst_file})


def disk_copy(session, dc_ref, src_file, dst_file):
    """Copies the source virtual disk to the destination."""
    LOG.debug("Copying virtual disk from %(src)s to %(dst)s.",
              {'src': src_file, 'dst': dst_file})
    copy_disk_task = session._call_method(
            session.vim,
            "CopyVirtualDisk_Task",
            session.vim.service_content.virtualDiskManager,
            sourceName=str(src_file),
            sourceDatacenter=dc_ref,
            destName=str(dst_file),
            destDatacenter=dc_ref,
            force=False)
    session._wait_for_task(copy_disk_task)
    LOG.info("Copied virtual disk from %(src)s to %(dst)s.",
             {'src': src_file, 'dst': dst_file})


def disk_delete(session, dc_ref, file_path):
    """Deletes a virtual disk."""
    LOG.debug("Deleting virtual disk %s", file_path)
    delete_disk_task = session._call_method(
            session.vim,
            "DeleteVirtualDisk_Task",
            session.vim.service_content.virtualDiskManager,
            name=str(file_path),
            datacenter=dc_ref)
    session._wait_for_task(delete_disk_task)
    LOG.info("Deleted virtual disk %s.", file_path)


def file_move(session, dc_ref, src_file, dst_file):
    """Moves the source file or folder to the destination.

    The list of possible faults that the server can return on error
    include:

    * CannotAccessFile: Thrown if the source file or folder cannot be
      moved because of insufficient permissions.
    * FileAlreadyExists: Thrown if a file with the given name already
      exists at the destination.
    * FileFault: Thrown if there is a generic file error
    * FileLocked: Thrown if the source file or folder is currently
      locked or in use.
    * FileNotFound: Thrown if the file or folder specified by sourceName
      is not found.
    * InvalidDatastore: Thrown if the operation cannot be performed on
      the source or destination datastores.
    * NoDiskSpace: Thrown if there is not enough space available on the
      destination datastore.
    * RuntimeFault: Thrown if any type of runtime fault is thrown that
      is not covered by the other faults; for example,
      a communication error.

    """
    LOG.debug("Moving file from %(src)s to %(dst)s.",
              {'src': src_file, 'dst': dst_file})
    vim = session.vim
    move_task = session._call_method(
            vim,
            "MoveDatastoreFile_Task",
            vim.service_content.fileManager,
            sourceName=str(src_file),
            sourceDatacenter=dc_ref,
            destinationName=str(dst_file),
            destinationDatacenter=dc_ref)
    session._wait_for_task(move_task)
    LOG.debug("File moved")


def search_datastore_spec(client_factory, file_name):
    """Builds the datastore search spec."""
    search_spec = client_factory.create('ns0:HostDatastoreBrowserSearchSpec')
    search_spec.matchPattern = [file_name]
    search_spec.details = client_factory.create('ns0:FileQueryFlags')
    search_spec.details.fileOwner = False
    search_spec.details.fileSize = True
    search_spec.details.fileType = False
    search_spec.details.modification = False
    return search_spec


def file_exists(session, ds_browser, ds_path, file_name):
    """Check if the file exists on the datastore."""
    client_factory = session.vim.client.factory
    search_spec = search_datastore_spec(client_factory, file_name)
    search_task = session._call_method(session.vim,
                                             "SearchDatastore_Task",
                                             ds_browser,
                                             datastorePath=str(ds_path),
                                             searchSpec=search_spec)
    try:
        task_info = session._wait_for_task(search_task)
    except vexc.FileNotFoundException:
        return False

    file_exists = (getattr(task_info.result, 'file', False) and
                   task_info.result.file[0].path == file_name)
    return file_exists


def file_size(session, ds_browser, ds_path, file_name):
    """Returns the size of the specified file."""
    client_factory = session.vim.client.factory
    search_spec = search_datastore_spec(client_factory, file_name)
    search_task = session._call_method(session.vim,
                                       "SearchDatastore_Task",
                                       ds_browser,
                                       datastorePath=str(ds_path),
                                       searchSpec=search_spec)
    task_info = session._wait_for_task(search_task)
    if hasattr(task_info.result, 'file'):
        return task_info.result.file[0].fileSize


def mkdir(session, ds_path, dc_ref):
    """Creates a directory at the path specified. If it is just "NAME",
    then a directory with this name is created at the topmost level of the
    DataStore.
    """
    LOG.debug("Creating directory with path %s", ds_path)
    session._call_method(session.vim, "MakeDirectory",
            session.vim.service_content.fileManager,
            name=str(ds_path), datacenter=dc_ref,
            createParentDirectories=True)
    LOG.debug("Created directory with path %s", ds_path)


def get_sub_folders(session, ds_browser, ds_path):
    """Return a set of subfolders for a path on a datastore.

    If the path does not exist then an empty set is returned.
    """
    search_task = session._call_method(
            session.vim,
            "SearchDatastore_Task",
            ds_browser,
            datastorePath=str(ds_path))
    try:
        task_info = session._wait_for_task(search_task)
    except vexc.FileNotFoundException:
        return set()
    # populate the folder entries
    if hasattr(task_info.result, 'file'):
        return set([file.path for file in task_info.result.file])
    return set()


def _filter_datastores_matching_storage_policy(session, data_stores,
                                               storage_policy):
    """Get datastores matching the given storage policy.

    :param data_stores: the list of retrieve result wrapped datastore objects
    :param storage_policy: the storage policy name
    :return: the list of datastores conforming to the given storage policy
    """
    profile_id = pbm.get_profile_id_by_name(session, storage_policy)
    if profile_id:
        factory = session.pbm.client.factory
        ds_mors = [oc.obj for oc in data_stores.objects]
        hubs = pbm.convert_datastores_to_hubs(factory, ds_mors)
        matching_hubs = pbm.filter_hubs_by_profile(session, hubs,
                                                   profile_id)
        if matching_hubs:
            matching_ds = pbm.filter_datastores_by_hubs(matching_hubs,
                                                        ds_mors)
            object_contents = [oc for oc in data_stores.objects
                               if oc.obj in matching_ds]
            data_stores.objects = object_contents
            return data_stores
    LOG.error("Unable to retrieve storage policy with name %s", storage_policy)


def _update_datacenter_cache_from_objects(session, dcs):
    """Updates the datastore/datacenter cache."""
    with vutil.WithRetrieval(session.vim, dcs) as dc_objs:
        for dco in dc_objs:
            dc_ref = dco.obj
            ds_refs = []
            prop_dict = vm_util.propset_dict(dco.propSet)
            name = prop_dict.get('name')
            vmFolder = prop_dict.get('vmFolder')
            datastore_refs = prop_dict.get('datastore')
            if datastore_refs:
                datastore_refs = datastore_refs.ManagedObjectReference
                for ds in datastore_refs:
                    ds_refs.append(ds.value)
            else:
                LOG.debug("Datacenter %s doesn't have any datastore "
                          "associated with it, ignoring it", name)
            for ds_ref in ds_refs:
                _DS_DC_MAPPING[ds_ref] = DcInfo(ref=dc_ref, name=name,
                                                vmFolder=vmFolder)


def get_dc_info(session, ds_ref):
    """Get the datacenter name and the reference."""
    dc_info = _DS_DC_MAPPING.get(ds_ref.value)
    if not dc_info:
        dcs = session._call_method(vim_util, "get_objects",
                "Datacenter", ["name", "datastore", "vmFolder"])
        _update_datacenter_cache_from_objects(session, dcs)
        dc_info = _DS_DC_MAPPING.get(ds_ref.value)
    return dc_info


def dc_cache_reset():
    global _DS_DC_MAPPING
    _DS_DC_MAPPING = {}


def get_connected_hosts(session, datastore):
    """Get all the hosts to which the datastore is connected.

    :param datastore: Reference to the datastore entity
    :return: List of managed object references of all connected
             hosts
    """
    host_mounts = session._call_method(vutil, 'get_object_property',
                                       datastore, 'host')
    if not hasattr(host_mounts, 'DatastoreHostMount'):
        return []

    connected_hosts = []
    for host_mount in host_mounts.DatastoreHostMount:
        connected_hosts.append(host_mount.key.value)

    return connected_hosts
