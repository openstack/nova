# Copyright (c) 2014-2017 Red Hat, Inc
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

import abc
import enum

import six

VERSION_LENGTH = 12
SUBTYPE_LENGTH = 4

AUTH_STATUS_FAIL = b"\x00"
AUTH_STATUS_PASS = b"\x01"


class AuthType(enum.IntEnum):

    INVALID = 0
    NONE = 1
    VNC = 2
    RA2 = 5
    RA2NE = 6
    TIGHT = 16
    ULTRA = 17
    TLS = 18  # Used by VINO
    VENCRYPT = 19  # Used by VeNCrypt and QEMU
    SASL = 20  # SASL type used by VINO and QEMU
    ARD = 30  # Apple remote desktop (screen sharing)
    MSLOGON = 0xfffffffa  # Used by UltraVNC


@six.add_metaclass(abc.ABCMeta)
class RFBAuthScheme(object):

    @abc.abstractmethod
    def security_type(self):
        """Return the security type supported by this scheme

        Returns the nova.console.rfb.auth.AuthType.XX
        constant representing the scheme implemented.
        """
        pass

    @abc.abstractmethod
    def security_handshake(self, compute_sock):
        """Perform security-type-specific functionality.

        This method is expected to return the socket-like
        object used to communicate with the server securely.

        Should raise exception.RFBAuthHandshakeFailed if
        an error occurs

        :param compute_sock: socket connected to the compute node instance
        """
        pass
