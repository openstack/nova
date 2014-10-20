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
import posixpath

from oslo.vmware import exceptions as vexc

from nova import exception
from nova.i18n import _
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)
ALLOWED_DATASTORE_TYPES = ['VMFS', 'NFS']


class Datastore(object):

    def __init__(self, ref, name, capacity=None, freespace=None):
        """Datastore object holds ref and name together for convenience.

        :param ref: a vSphere reference to a datastore
        :param name: vSphere unique name for this datastore
        :param capacity: (optional) capacity in bytes of this datastore
        :param freespace: (optional) free space in bytes of datastore
        """
        if name is None:
            raise ValueError(_("Datastore name cannot be None"))
        if ref is None:
            raise ValueError(_("Datastore reference cannot be None"))
        if freespace is not None and capacity is None:
            raise ValueError(_("Invalid capacity"))
        if capacity is not None and freespace is not None:
            if capacity < freespace:
                raise ValueError(_("Capacity is smaller than free space"))

        self._ref = ref
        self._name = name
        self._capacity = capacity
        self._freespace = freespace

    @property
    def ref(self):
        return self._ref

    @property
    def name(self):
        return self._name

    @property
    def capacity(self):
        return self._capacity

    @property
    def freespace(self):
        return self._freespace

    def build_path(self, *paths):
        """Constructs and returns a DatastorePath.

        :param paths: list of path components, for constructing a path relative
                      to the root directory of the datastore
        :return: a DatastorePath object
        """
        return DatastorePath(self._name, *paths)

    def __str__(self):
        return '[%s]' % self._name


class DatastorePath(object):
    """Class for representing a directory or file path in a vSphere datatore.

    This provides various helper methods to access components and useful
    variants of the datastore path.

    Example usage:

    DatastorePath("datastore1", "_base/foo", "foo.vmdk") creates an
    object that describes the "[datastore1] _base/foo/foo.vmdk" datastore
    file path to a virtual disk.

    Note:

    * Datastore path representations always uses forward slash as separator
      (hence the use of the posixpath module).
    * Datastore names are enclosed in square brackets.
    * Path part of datastore path is relative to the root directory
      of the datastore, and is always separated from the [ds_name] part with
      a single space.

    """

    VMDK_EXTENSION = "vmdk"

    def __init__(self, datastore_name, *paths):
        if datastore_name is None or datastore_name == '':
            raise ValueError(_("datastore name empty"))
        self._datastore_name = datastore_name
        self._rel_path = ''
        if paths:
            if None in paths:
                raise ValueError(_("path component cannot be None"))
            self._rel_path = posixpath.join(*paths)

    def __str__(self):
        """Full datastore path to the file or directory."""
        if self._rel_path != '':
            return "[%s] %s" % (self._datastore_name, self.rel_path)
        return "[%s]" % self._datastore_name

    def __repr__(self):
        return "%s(%s, %s)" % (self.__class__.__name__,
                               self.datastore, self.rel_path)

    @property
    def datastore(self):
        return self._datastore_name

    @property
    def parent(self):
        return DatastorePath(self.datastore, posixpath.dirname(self._rel_path))

    @property
    def basename(self):
        return posixpath.basename(self._rel_path)

    @property
    def dirname(self):
        return posixpath.dirname(self._rel_path)

    @property
    def rel_path(self):
        return self._rel_path

    def join(self, *paths):
        if paths:
            if None in paths:
                raise ValueError(_("path component cannot be None"))
            return DatastorePath(self.datastore,
                                 posixpath.join(self._rel_path, *paths))
        return self

    def __eq__(self, other):
        return (isinstance(other, DatastorePath) and
                self._datastore_name == other._datastore_name and
                self._rel_path == other._rel_path)

    def __hash__(self):
        return str(self).__hash__()

    @classmethod
    def parse(cls, datastore_path):
        """Constructs a DatastorePath object given a datastore path string."""
        if not datastore_path:
            raise ValueError(_("datastore path empty"))

        spl = datastore_path.split('[', 1)[1].split(']', 1)
        path = ""
        if len(spl) == 1:
            datastore_name = spl[0]
        else:
            datastore_name, path = spl
        return cls(datastore_name, path.strip())


# NOTE(mdbooth): this convenience function is temporarily duplicated in
# vm_util. The correct fix is to handle paginated results as they are returned
# from the relevant vim_util function. However, vim_util is currently
# effectively deprecated as we migrate to oslo.vmware. This duplication will be
# removed when we fix it properly in oslo.vmware.
def _get_token(results):
    """Get the token from the property results."""
    return getattr(results, 'token', None)


def _select_datastore(data_stores, best_match, datastore_regex=None):
    """Find the most preferable datastore in a given RetrieveResult object.

    :param data_stores: a RetrieveResult object from vSphere API call
    :param best_match: the current best match for datastore
    :param datastore_regex: an optional regular expression to match names
    :return: datastore_ref, datastore_name, capacity, freespace
    """

    # data_stores is actually a RetrieveResult object from vSphere API call
    for obj_content in data_stores.objects:
        # the propset attribute "need not be set" by returning API
        if not hasattr(obj_content, 'propSet'):
            continue

        propdict = vm_util.propset_dict(obj_content.propSet)
        if _is_datastore_valid(propdict, datastore_regex):
            new_ds = Datastore(
                    ref=obj_content.obj,
                    name=propdict['summary.name'],
                    capacity=propdict['summary.capacity'],
                    freespace=propdict['summary.freeSpace'])
            # favor datastores with more free space
            if (best_match is None or
                new_ds.freespace > best_match.freespace):
                best_match = new_ds

    return best_match


def _is_datastore_valid(propdict, datastore_regex):
    """Checks if a datastore is valid based on the following criteria.

       Criteria:
       - Datastore is accessible
       - Datastore is not in maintenance mode (optional)
       - Datastore is of a supported disk type
       - Datastore matches the supplied regex (optional)

       :param propdict: datastore summary dict
       :param datastore_regex : Regex to match the name of a datastore.
    """

    # Local storage identifier vSphere doesn't support CIFS or
    # vfat for datastores, therefore filtered
    return (propdict.get('summary.accessible') and
            (propdict.get('summary.maintenanceMode') is None or
             propdict.get('summary.maintenanceMode') == 'normal') and
            propdict['summary.type'] in ALLOWED_DATASTORE_TYPES and
            (datastore_regex is None or
             datastore_regex.match(propdict['summary.name'])))


def get_datastore(session, cluster, datastore_regex=None):
    """Get the datastore list and choose the most preferable one."""
    datastore_ret = session._call_method(
                                vim_util,
                                "get_dynamic_property", cluster,
                                "ClusterComputeResource", "datastore")
    # If there are no hosts in the cluster then an empty string is
    # returned
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
        best_match = _select_datastore(data_stores, best_match,
                                       datastore_regex)
        token = _get_token(data_stores)
        if not token:
            break
        data_stores = session._call_method(vim_util,
                                           "continue_to_get_objects",
                                           token)
    if best_match:
        return best_match
    if datastore_regex:
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
        if _is_datastore_valid(propdict, datastore_regex):
            allowed.append(Datastore(ref=obj_content.obj,
                                     name=propdict['summary.name']))

    return allowed


def get_available_datastores(session, cluster=None, datastore_regex=None):
    """Get the datastore list and choose the first local storage."""
    if cluster:
        mobj = cluster
        resource_type = "ClusterComputeResource"
    else:
        mobj = vm_util.get_host_ref(session)
        resource_type = "HostSystem"
    ds = session._call_method(vim_util, "get_dynamic_property", mobj,
                              resource_type, "datastore")
    if not ds:
        return []
    data_store_mors = ds.ManagedObjectReference
    # NOTE(garyk): use utility method to retrieve remote objects
    data_stores = session._call_method(vim_util,
            "get_properties_for_a_collection_of_objects",
            "Datastore", data_store_mors,
            ["summary.type", "summary.name", "summary.accessible",
            "summary.maintenanceMode"])

    allowed = []
    while data_stores:
        allowed.extend(_get_allowed_datastores(data_stores, datastore_regex))
        token = _get_token(data_stores)
        if not token:
            break

        data_stores = session._call_method(vim_util,
                                           "continue_to_get_objects",
                                           token)
    return allowed


def file_delete(session, ds_path, dc_ref):
    LOG.debug("Deleting the datastore file %s", ds_path)
    vim = session._get_vim()
    file_delete_task = session._call_method(
            session._get_vim(),
            "DeleteDatastoreFile_Task",
            vim.service_content.fileManager,
            name=str(ds_path),
            datacenter=dc_ref)
    session._wait_for_task(file_delete_task)
    LOG.debug("Deleted the datastore file")


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
    vim = session._get_vim()
    move_task = session._call_method(
            session._get_vim(),
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
    return search_spec


def file_exists(session, ds_browser, ds_path, file_name):
    """Check if the file exists on the datastore."""
    client_factory = session._get_vim().client.factory
    search_spec = search_datastore_spec(client_factory, file_name)
    search_task = session._call_method(session._get_vim(),
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


def mkdir(session, ds_path, dc_ref):
    """Creates a directory at the path specified. If it is just "NAME",
    then a directory with this name is created at the topmost level of the
    DataStore.
    """
    LOG.debug("Creating directory with path %s", ds_path)
    session._call_method(session._get_vim(), "MakeDirectory",
            session._get_vim().service_content.fileManager,
            name=str(ds_path), datacenter=dc_ref,
            createParentDirectories=True)
    LOG.debug("Created directory with path %s", ds_path)


def get_sub_folders(session, ds_browser, ds_path):
    """Return a set of subfolders for a path on a datastore.

    If the path does not exist then an empty set is returned.
    """
    search_task = session._call_method(
            session._get_vim(),
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
