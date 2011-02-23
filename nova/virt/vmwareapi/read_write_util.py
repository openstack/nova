# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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

""" Classes to handle image files

Collection of classes to handle image upload/download to/from Image service
(like Glance image storage and retrieval service) from/to ESX/ESXi server.

Also a class is available that acts as Fake image service. It uses local
file system for storage.

"""

import httplib
import json
import logging
import os
import urllib
import urllib2
import urlparse

from nova import flags
from nova import utils
from nova.auth.manager import AuthManager

FLAGS = flags.FLAGS

READ_CHUNKSIZE = 2 * 1024 * 1024

USER_AGENT = "OpenStack-ESX-Adapter"

LOG = logging.getLogger("nova.virt.vmwareapi.read_write_util")


class ImageServiceFile:
    """The base image service Class"""

    def __init__(self, file_handle):
        """Initialize the file handle."""
        self.eof = False
        self.file_handle = file_handle

    def write(self, data):
        """Write data to the file"""
        raise NotImplementedError

    def read(self, chunk_size=READ_CHUNKSIZE):
        """Read a chunk of data from the file"""
        raise NotImplementedError

    def get_size(self):
        """Get the size of the file whose data is to be read"""
        raise NotImplementedError

    def set_eof(self, eof):
        """Set the end of file marker."""
        self.eof = eof

    def get_eof(self):
        """Check if the file end has been reached or not."""
        return self.eof

    def close(self):
        """Close the file handle."""
        try:
            self.file_handle.close()
        except Exception:
            pass

    def get_image_properties(self):
        """Get the image properties"""
        raise NotImplementedError

    def __del__(self):
        """Destructor. Close the file handle if the same has been forgotten."""
        self.close()


class GlanceHTTPWriteFile(ImageServiceFile):
    """Glance file write handler Class"""

    def __init__(self, host, port, image_id, file_size, os_type, adapter_type,
                 version=1, scheme="http"):
        """Initialize with the glance host specifics."""
        base_url = "%s://%s:%s/images/%s" % (scheme, host, port, image_id)
        (scheme, netloc, path, params, query, fragment) = \
            urlparse.urlparse(base_url)
        if scheme == "http":
            conn = httplib.HTTPConnection(netloc)
        elif scheme == "https":
            conn = httplib.HTTPSConnection(netloc)
        conn.putrequest("PUT", path)
        conn.putheader("User-Agent", USER_AGENT)
        conn.putheader("Content-Length", file_size)
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("x-image-meta-store", "file")
        conn.putheader("x-image-meta-is_public", "True")
        conn.putheader("x-image-meta-type", "raw")
        conn.putheader("x-image-meta-size", file_size)
        conn.putheader("x-image-meta-property-kernel_id", "")
        conn.putheader("x-image-meta-property-ramdisk_id", "")
        conn.putheader("x-image-meta-property-vmware_ostype", os_type)
        conn.putheader("x-image-meta-property-vmware_adaptertype",
                       adapter_type)
        conn.putheader("x-image-meta-property-vmware_image_version", version)
        conn.endheaders()
        ImageServiceFile.__init__(self, conn)

    def write(self, data):
        """Write data to the file"""
        self.file_handle.send(data)


class GlanceHTTPReadFile(ImageServiceFile):
    """Glance file read handler Class"""

    def __init__(self, host, port, image_id, scheme="http"):
        """Initialize with the glance host specifics."""
        base_url = "%s://%s:%s/images/%s" % (scheme, host, port,
                                           urllib.pathname2url(image_id))
        headers = {'User-Agent': USER_AGENT}
        request = urllib2.Request(base_url, None, headers)
        conn = urllib2.urlopen(request)
        ImageServiceFile.__init__(self, conn)

    def read(self, chunk_size=READ_CHUNKSIZE):
        """Read a chunk of data."""
        return self.file_handle.read(chunk_size)

    def get_size(self):
        """Get the size of the file to be read."""
        return self.file_handle.headers.get("X-Image-Meta-Size", -1)

    def get_image_properties(self):
        """Get the image properties like say OS Type and the Adapter Type"""
        return {"vmware_ostype":
                    self.file_handle.headers.get(
                            "X-Image-Meta-Property-Vmware_ostype"),
                "vmware_adaptertype":
                    self.file_handle.headers.get(
                            "X-Image-Meta-Property-Vmware_adaptertype"),
                "vmware_image_version":
                    self.file_handle.headers.get(
                            "X-Image-Meta-Property-Vmware_image_version")}


class FakeFileRead(ImageServiceFile):
    """Local file read handler class"""

    def __init__(self, path):
        """Initialize the file path"""
        self.path = path
        file_handle = open(path, "rb")
        ImageServiceFile.__init__(self, file_handle)

    def get_size(self):
        """Get size of the file to be read"""
        return os.path.getsize(os.path.abspath(self.path))

    def read(self, chunk_size=READ_CHUNKSIZE):
        """Read a chunk of data"""
        return self.file_handle.read(chunk_size)

    def get_image_properties(self):
        """Get the image properties like say OS Type and the Adapter Type"""
        return {"vmware_ostype": "otherGuest",
                "vmware_adaptertype": "lsiLogic",
                "vmware_image_version": "1"}


class FakeFileWrite(ImageServiceFile):
    """Local file write handler Class"""

    def __init__(self, path):
        """Initialize the file path."""
        file_handle = open(path, "wb")
        ImageServiceFile.__init__(self, file_handle)

    def write(self, data):
        """Write data to the file."""
        self.file_handle.write(data)


class VMwareHTTPFile(object):
    """Base Class for HTTP file."""

    def __init__(self, file_handle):
        """Intialize the file handle."""
        self.eof = False
        self.file_handle = file_handle

    def set_eof(self, eof):
        """Set the end of file marker."""
        self.eof = eof

    def get_eof(self):
        """Check if the end of file has been reached."""
        return self.eof

    def close(self):
        """Close the file handle."""
        try:
            self.file_handle.close()
        except Exception:
            pass

    def __del__(self):
        """Destructor. Close the file handle if the same has been forgotten."""
        self.close()

    def _build_vim_cookie_headers(self, vim_cookies):
        """Build ESX host session cookie headers."""
        cookie = str(vim_cookies).split(":")[1].strip()
        cookie = cookie[:cookie.find(';')]
        return cookie

    def write(self, data):
        """Write data to the file."""
        raise NotImplementedError

    def read(self, chunk_size=READ_CHUNKSIZE):
        """Read a chunk of data."""
        raise NotImplementedError

    def get_size(self):
        """Get size of the file to be read."""
        raise NotImplementedError


class VMWareHTTPWriteFile(VMwareHTTPFile):
    """VMWare file write handler Class"""

    def __init__(self, host, data_center_name, datastore_name, cookies,
                 file_path, file_size, scheme="https"):
        """Initialize the file specifics."""
        base_url = "%s://%s/folder/%s" % (scheme, host, file_path)
        param_list = {"dcPath": data_center_name, "dsName": datastore_name}
        base_url = base_url + "?" + urllib.urlencode(param_list)
        (scheme, netloc, path, params, query, fragment) = \
            urlparse.urlparse(base_url)
        if scheme == "http":
            conn = httplib.HTTPConnection(netloc)
        elif scheme == "https":
            conn = httplib.HTTPSConnection(netloc)
        conn.putrequest("PUT", path + "?" + query)
        conn.putheader("User-Agent", USER_AGENT)
        conn.putheader("Content-Length", file_size)
        conn.putheader("Cookie", self._build_vim_cookie_headers(cookies))
        conn.endheaders()
        self.conn = conn
        VMwareHTTPFile.__init__(self, conn)

    def write(self, data):
        """Write to the file."""
        self.file_handle.send(data)

    def close(self):
        """Get the response and close the connection"""
        try:
            self.conn.getresponse()
        except Exception, excep:
            LOG.debug(_("Exception during close of connection in "
                      "VMWareHTTpWrite. Exception is %s") % excep)
        super(VMWareHTTPWriteFile, self).close()


class VmWareHTTPReadFile(VMwareHTTPFile):
    """VMWare file read handler Class"""

    def __init__(self, host, data_center_name, datastore_name, cookies,
                 file_path, scheme="https"):
        """Initialize the file specifics."""
        base_url = "%s://%s/folder/%s" % (scheme, host,
                                          urllib.pathname2url(file_path))
        param_list = {"dcPath": data_center_name, "dsName": datastore_name}
        base_url = base_url + "?" + urllib.urlencode(param_list)
        headers = {'User-Agent': USER_AGENT,
                   'Cookie': self._build_vim_cookie_headers(cookies)}
        request = urllib2.Request(base_url, None, headers)
        conn = urllib2.urlopen(request)
        VMwareHTTPFile.__init__(self, conn)

    def read(self, chunk_size=READ_CHUNKSIZE):
        """Read a chunk of data."""
        return self.file_handle.read(chunk_size)

    def get_size(self):
        """Get size of the file to be read."""
        return self.file_handle.headers.get("Content-Length", -1)
