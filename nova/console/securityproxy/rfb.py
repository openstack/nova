# Copyright (c) 2014-2016 Red Hat, Inc
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

import struct

from oslo_config import cfg
from oslo_log import log as logging
import six

from nova.console.rfb import auth
from nova.console.rfb import auths
from nova.console.securityproxy import base
from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class RFBSecurityProxy(base.SecurityProxy):
    """RFB Security Proxy Negotiation Helper.

    This class proxies the initial setup of the RFB connection between the
    client and the server. Then, when the RFB security negotiation step
    arrives, it intercepts the communication, posing as a server with the
    "None" authentication type to the client, and acting as a client (via
    the methods below) to the server. After security negotiation, normal
    proxying can be used.

    Note: this code mandates RFB version 3.8, since this is supported by any
    client and server impl written in the past 10+ years.

    See the general RFB specification at:

      https://tools.ietf.org/html/rfc6143

    See an updated, maintained RDB specification at:

      https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
    """

    def __init__(self):
        self.auth_schemes = auths.RFBAuthSchemeList()

    def _make_var_str(self, message):
        message_str = six.text_type(message)
        message_bytes = message_str.encode('utf-8')
        message_len = struct.pack("!I", len(message_bytes))
        return message_len + message_bytes

    def _fail(self, tenant_sock, compute_sock, message):
        # Tell the client there's been a problem
        result_code = struct.pack("!I", 1)
        tenant_sock.sendall(result_code + self._make_var_str(message))

        if compute_sock is not None:
            # Tell the server that there's been a problem
            # by sending the "Invalid" security type
            compute_sock.sendall(auth.AUTH_STATUS_FAIL)

    @staticmethod
    def _parse_version(version_str):
        r"""Convert a version string to a float.

        >>> RFBSecurityProxy._parse_version('RFB 003.008\n')
        0.2
        """
        maj_str = version_str[4:7]
        min_str = version_str[8:11]

        return float("%d.%d" % (int(maj_str), int(min_str)))

    def connect(self, tenant_sock, compute_sock):
        """Initiate the RFB connection process.

        This method performs the initial ProtocolVersion
        and Security messaging, and returns the socket-like
        object to use to communicate with the server securely.
        If an error occurs SecurityProxyNegotiationFailed
        will be raised.
        """

        def recv(sock, num):
            b = sock.recv(num)
            if len(b) != num:
                reason = _("Incorrect read from socket, wanted %(wanted)d "
                           "bytes but got %(got)d. Socket returned "
                           "%(result)r") % {'wanted': num, 'got': len(b),
                                            'result': b}
                raise exception.RFBAuthHandshakeFailed(reason=reason)
            return b

        # Negotiate version with compute server
        compute_version = recv(compute_sock, auth.VERSION_LENGTH)
        LOG.debug("Got version string '%s' from compute node",
                  compute_version[:-1])

        if self._parse_version(compute_version) != 3.8:
            reason = _("Security proxying requires RFB protocol "
                       "version 3.8, but server sent %s"), compute_version[:-1]
            raise exception.SecurityProxyNegotiationFailed(reason=reason)
        compute_sock.sendall(compute_version)

        # Negotiate version with tenant
        tenant_sock.sendall(compute_version)
        tenant_version = recv(tenant_sock, auth.VERSION_LENGTH)
        LOG.debug("Got version string '%s' from tenant",
                  tenant_version[:-1])

        if self._parse_version(tenant_version) != 3.8:
            reason = _("Security proxying requires RFB protocol version "
                       "3.8, but tenant asked for %s"), tenant_version[:-1]
            raise exception.SecurityProxyNegotiationFailed(reason=reason)

        # Negotiate security with server
        permitted_auth_types_cnt = six.byte2int(recv(compute_sock, 1))

        if permitted_auth_types_cnt == 0:
            # Decode the reason why the request failed
            reason_len_raw = recv(compute_sock, 4)
            reason_len = struct.unpack('!I', reason_len_raw)[0]
            reason = recv(compute_sock, reason_len)

            tenant_sock.sendall(auth.AUTH_STATUS_FAIL +
                                reason_len_raw + reason)

            raise exception.SecurityProxyNegotiationFailed(reason=reason)

        f = recv(compute_sock, permitted_auth_types_cnt)
        permitted_auth_types = []
        for auth_type in f:
            if isinstance(auth_type, six.string_types):
                auth_type = ord(auth_type)
            permitted_auth_types.append(auth_type)

        LOG.debug("The server sent security types %s", permitted_auth_types)

        # Negotiate security with client before we say "ok" to the server
        # send 1:[None]
        tenant_sock.sendall(auth.AUTH_STATUS_PASS +
                            six.int2byte(auth.AuthType.NONE))
        client_auth = six.byte2int(recv(tenant_sock, 1))

        if client_auth != auth.AuthType.NONE:
            self._fail(tenant_sock, compute_sock,
                       _("Only the security type None (%d) is supported") %
                       auth.AuthType.NONE)

            reason = _("Client requested a security type other than None "
                       "(%(none_code)d): %(auth_type)s") % {
                           'auth_type': client_auth,
                           'none_code': auth.AuthType.NONE}
            raise exception.SecurityProxyNegotiationFailed(reason=reason)

        try:
            scheme = self.auth_schemes.find_scheme(permitted_auth_types)
        except exception.RFBAuthNoAvailableScheme as e:
            # Intentionally don't tell client what really failed
            # as that's information leakage
            self._fail(tenant_sock, compute_sock,
                       _("Unable to negotiate security with server"))
            raise exception.SecurityProxyNegotiationFailed(
                reason=_("No compute auth available: %s") % six.text_type(e))

        compute_sock.sendall(six.int2byte(scheme.security_type()))

        LOG.debug("Using security type %d with server, None with client",
                  scheme.security_type())

        try:
            compute_sock = scheme.security_handshake(compute_sock)
        except exception.RFBAuthHandshakeFailed as e:
            # Intentionally don't tell client what really failed
            # as that's information leakage
            self._fail(tenant_sock, None,
                       _("Unable to negotiate security with server"))
            LOG.debug("Auth failed %s", six.text_type(e))
            raise exception.SecurityProxyNegotiationFailed(
                reason=_("Auth handshake failed"))

        LOG.info("Finished security handshake, resuming normal proxy "
                 "mode using secured socket")

        # we can just proxy the security result -- if the server security
        # negotiation fails, we want the client to think it has failed

        return compute_sock
