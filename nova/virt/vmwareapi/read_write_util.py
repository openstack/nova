# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

"""Classes to handle image files

Collection of classes to handle image upload/download to/from Image service
(like Glance image storage and retrieval service) from/to ESX/ESXi server.

"""

import urllib

from oslo_utils import netutils
from oslo_vmware import rw_handles


class VMwareHTTPReadFile(rw_handles.FileHandle):
    """VMware file read handler class."""

    def __init__(self, host, port, data_center_name, datastore_name, cookies,
                 file_path, scheme="https"):
        self._base_url = self._get_base_url(scheme, host, port, file_path)
        param_list = {"dcPath": data_center_name, "dsName": datastore_name}
        self._base_url = self._base_url + "?" + urllib.urlencode(param_list)
        self._conn = self._create_read_connection(self._base_url,
                                                  cookies=cookies)
        rw_handles.FileHandle.__init__(self, self._conn)

    def read(self, chunk_size):
        return self._file_handle.read(rw_handles.READ_CHUNKSIZE)

    def _get_base_url(self, scheme, host, port, file_path):
        if netutils.is_valid_ipv6(host):
            base_url = "%s://[%s]:%s/folder/%s" % (scheme, host, port,
                                                urllib.pathname2url(file_path))
        else:
            base_url = "%s://%s:%s/folder/%s" % (scheme, host, port,
                                              urllib.pathname2url(file_path))
        return base_url

    def get_size(self):
        """Get size of the file to be read."""
        return self._file_handle.headers.get("Content-Length", -1)
