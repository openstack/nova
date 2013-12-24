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

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)


def build_datastore_path(datastore_name, path):
    """Build the datastore compliant path."""
    return "[%s] %s" % (datastore_name, path)


def split_datastore_path(datastore_path):
    """Return the datastore and path from a datastore_path.

    Split the VMware style datastore path to get the Datastore
    name and the entity path.
    """
    spl = datastore_path.split('[', 1)[1].split(']', 1)
    path = ""
    if len(spl) == 1:
        datastore_name = spl[0]
    else:
        datastore_name, path = spl
    return datastore_name, path.strip()


def file_delete(session, datastore_path, dc_ref):
    LOG.debug(_("Deleting the datastore file %s"), datastore_path)
    vim = session._get_vim()
    file_delete_task = session._call_method(
            session._get_vim(),
            "DeleteDatastoreFile_Task",
            vim.get_service_content().fileManager,
            name=datastore_path,
            datacenter=dc_ref)
    session._wait_for_task(file_delete_task)
    LOG.debug(_("Deleted the datastore file"))


def file_move(session, dc_ref, src_file, dst_file):
    """Moves the source file or folder to the destination.

    The list of possible faults that the server can return on error
    include:
    - CannotAccessFile: Thrown if the source file or folder cannot be
                        moved because of insufficient permissions.
    - FileAlreadyExists: Thrown if a file with the given name already
                         exists at the destination.
    - FileFault: Thrown if there is a generic file error
    - FileLocked: Thrown if the source file or folder is currently
                  locked or in use.
    - FileNotFound: Thrown if the file or folder specified by sourceName
                    is not found.
    - InvalidDatastore: Thrown if the operation cannot be performed on
                        the source or destination datastores.
    - NoDiskSpace: Thrown if there is not enough space available on the
                   destination datastore.
    - RuntimeFault: Thrown if any type of runtime fault is thrown that
                    is not covered by the other faults; for example,
                    a communication error.
    """
    LOG.debug(_("Moving file from %(src)s to %(dst)s."),
              {'src': src_file, 'dst': dst_file})
    vim = session._get_vim()
    move_task = session._call_method(
            session._get_vim(),
            "MoveDatastoreFile_Task",
            vim.get_service_content().fileManager,
            sourceName=src_file,
            sourceDatacenter=dc_ref,
            destinationName=dst_file,
            destinationDatacenter=dc_ref)
    session._wait_for_task(move_task)
    LOG.debug(_("File moved"))


def file_exists(session, ds_browser, ds_path, file_name):
    """Check if the file exists on the datastore."""
    client_factory = session._get_vim().client.factory
    search_spec = vm_util.search_datastore_spec(client_factory, file_name)
    search_task = session._call_method(session._get_vim(),
                                             "SearchDatastore_Task",
                                             ds_browser,
                                             datastorePath=ds_path,
                                             searchSpec=search_spec)
    try:
        task_info = session._wait_for_task(search_task)
    except error_util.FileNotFoundException:
        return False

    file_exists = (getattr(task_info.result, 'file', False) and
                   task_info.result.file[0].path == file_name)
    return file_exists


def mkdir(session, ds_path, dc_ref):
    """Creates a directory at the path specified. If it is just "NAME",
    then a directory with this name is created at the topmost level of the
    DataStore.
    """
    LOG.debug(_("Creating directory with path %s"), ds_path)
    session._call_method(session._get_vim(), "MakeDirectory",
            session._get_vim().get_service_content().fileManager,
            name=ds_path, datacenter=dc_ref,
            createParentDirectories=True)
    LOG.debug(_("Created directory with path %s"), ds_path)
