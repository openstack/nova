# Copyright (c) 2014-2016 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import enum
import ssl
import struct

from oslo_config import cfg
from oslo_log import log as logging
import six

from nova.console.rfb import auth
from nova import exception
from nova.i18n import _

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class AuthVeNCryptSubtype(enum.IntEnum):
    """Possible VeNCrypt subtypes.

    From https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst
    """

    PLAIN = 256
    TLSNONE = 257
    TLSVNC = 258
    TLSPLAIN = 259
    X509NONE = 260
    X509VNC = 261
    X509PLAIN = 262
    X509SASL = 263
    TLSSASL = 264


class RFBAuthSchemeVeNCrypt(auth.RFBAuthScheme):
    """A security proxy helper which uses VeNCrypt.

    This security proxy helper uses the VeNCrypt security
    type to achieve SSL/TLS-secured VNC.  It supports both
    standard SSL/TLS encryption and SSL/TLS encryption with
    x509 authentication.

    Refer to https://www.berrange.com/~dan/vencrypt.txt for
    a brief overview of the protocol.
    """

    def security_type(self):
        return auth.AuthType.VENCRYPT

    def security_handshake(self, compute_sock):
        def recv(num):
            b = compute_sock.recv(num)
            if len(b) != num:
                reason = _("Short read from compute socket, wanted "
                           "%(wanted)d bytes but got %(got)d") % {
                               'wanted': num, 'got': len(b)}
                raise exception.RFBAuthHandshakeFailed(reason=reason)
            return b

        # get the VeNCrypt version from the server
        maj_ver = ord(recv(1))
        min_ver = ord(recv(1))

        LOG.debug("Server sent VeNCrypt version "
                  "%(maj)s.%(min)s", {'maj': maj_ver, 'min': min_ver})

        if maj_ver != 0 or min_ver != 2:
            reason = _("Only VeNCrypt version 0.2 is supported by this "
                       "proxy, but the server wanted to use version "
                       "%(maj)s.%(min)s") % {'maj': maj_ver, 'min': min_ver}
            raise exception.RFBAuthHandshakeFailed(reason=reason)

        # use version 0.2
        compute_sock.sendall(b"\x00\x02")

        can_use_version = ord(recv(1))

        if can_use_version > 0:
            reason = _("Server could not use VeNCrypt version 0.2")
            raise exception.RFBAuthHandshakeFailed(reason=reason)

        # get the supported sub-auth types
        sub_types_cnt = ord(recv(1))
        sub_types_raw = recv(sub_types_cnt * auth.SUBTYPE_LENGTH)
        sub_types = struct.unpack('!' + str(sub_types_cnt) + 'I',
                                  sub_types_raw)

        LOG.debug("Server supports VeNCrypt sub-types %s", sub_types)

        # We use X509None as we're only seeking to encrypt the channel (ruling
        # out PLAIN) and prevent MITM (ruling out TLS*, which uses trivially
        # MITM'd Anonymous Diffie Hellmann (DH) cyphers)
        if AuthVeNCryptSubtype.X509NONE not in sub_types:
            reason = _("Server does not support the x509None (%s) VeNCrypt"
                       " sub-auth type") % \
                       AuthVeNCryptSubtype.X509NONE
            raise exception.RFBAuthHandshakeFailed(reason=reason)

        LOG.debug("Attempting to use the x509None (%s) auth sub-type",
                  AuthVeNCryptSubtype.X509NONE)

        compute_sock.sendall(struct.pack(
            '!I', AuthVeNCryptSubtype.X509NONE))

        # NB(sross): the spec is missing a U8 here that's used in
        # multiple implementations (e.g. QEMU, GTK-VNC).  1 means
        # acceptance, 0 means failure (unlike the rest of RFB)
        auth_accepted = ord(recv(1))
        if auth_accepted == 0:
            reason = _("Server didn't accept the requested auth sub-type")
            raise exception.RFBAuthHandshakeFailed(reason=reason)

        LOG.debug("Server accepted the requested sub-auth type")

        if (CONF.vnc.vencrypt_client_key and
                CONF.vnc.vencrypt_client_cert):
            client_key = CONF.vnc.vencrypt_client_key
            client_cert = CONF.vnc.vencrypt_client_cert
        else:
            client_key = None
            client_cert = None

        try:
            wrapped_sock = ssl.wrap_socket(
                compute_sock,
                keyfile=client_key,
                certfile=client_cert,
                server_side=False,
                cert_reqs=ssl.CERT_REQUIRED,
                ca_certs=CONF.vnc.vencrypt_ca_certs)

            LOG.info("VeNCrypt security handshake accepted")
            return wrapped_sock

        except ssl.SSLError as e:
            reason = _("Error establishing TLS connection to server: %s") % (
                six.text_type(e))
            raise exception.RFBAuthHandshakeFailed(reason=reason)
