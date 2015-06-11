#
# Copyright (C) 2014 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

from oslo_utils import strutils

from nova import exception

FORMAT_RAW = "raw"
FORMAT_QCOW2 = "qcow2"
FORMAT_PLOOP = "ploop"

ALL_FORMATS = [
    FORMAT_RAW,
    FORMAT_QCOW2,
    FORMAT_PLOOP,
]


class Image(object):
    """Base class for all image types.

    All image types have a format, though for many of
    them only a subset of formats will commonly be
    used. For example, block devices are almost
    always going to be FORMAT_RAW. Though it is in
    fact possible from a technical POV to store a
    qcow2 data inside a block device, Nova does not
    (at this time) make use of such possibilities.
    """

    def __init__(self, format):
        """Create a new abstract image

        :param format: one of the format constants
        """
        super(Image, self).__init__()

        self.format = format

        if format not in ALL_FORMATS:
            raise exception.InvalidImageFormat(format=format)

    def __repr__(self):
        msg = "<" + self.__class__.__name__ + ":" + str(self.__dict__) + ">"
        return strutils.mask_password(msg)

    def __eq__(self, other):
        return ((self.__class__ == other.__class__) and
                (self.__dict__ == other.__dict__))

    def __hash__(self):
        return hash(str(self.__dict__))


class LocalImage(Image):
    """Class for images that are paths within the
    local filesystem
    """

    def __init__(self, path, format):
        """Create a new local image object

        :param path: qualified filename of the image
        :param format: one of the format constants
        """
        super(LocalImage, self).__init__(format)

        self.path = path


class LocalFileImage(LocalImage):
    """Class for images that are files on a locally
    accessible filesystem
    """

    def __init__(self, path, format):
        """Create a new local file object

        :param path: qualified filename of the image
        :param format: one of the format constants
        """
        super(LocalFileImage, self).__init__(path, format)


class LocalBlockImage(LocalImage):
    """Class for images that are block devices on
    the local host
    """

    def __init__(self, path):
        """Create a new local file object

        :param path: qualified filename of the image
        """
        super(LocalBlockImage, self).__init__(path, FORMAT_RAW)


class RBDImage(Image):
    """Class for images that are volumes on a remote
    RBD server
    """

    def __init__(self, name, pool, user, password, servers):
        """Create a new RBD image object

        :param name: name of the image relative to the pool
        :param pool: name of the pool holding the image
        :param user: username to authenticate as
        :param password: credentials for authenticating with
        :param servers: list of hostnames for the server
        """
        super(RBDImage, self).__init__(FORMAT_RAW)

        self.name = name
        self.pool = pool
        self.user = user
        self.password = password
        self.servers = servers
