# Copyright (c) 2016 VMware Inc.
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
import base64
import hashlib
import os
import socket
import ssl

from nova.console.securityproxy import base
from nova import exception


class MksSecurityProxy(base.SecurityProxy):
    VMAD_OK = 200
    VMAD_WELCOME = 220
    VMAD_LOGINOK = 230
    VMAD_NEEDPASSWD = 331
    VMAD_USER_CMD = "USER"
    VMAD_PASS_CMD = "PASS"
    VMAD_THUMB_CMD = "THUMBPRINT"
    VMAD_CONNECT_CMD = "CONNECT"

    def connect(self, tenant_sock, compute_sock):
        mks_auth = tenant_sock.reqhandler.internal_access_path_data
        ticket = mks_auth['ticket']
        cfg_file = mks_auth['cfgFile']
        thumbprint = mks_auth['thumbprint']

        def expect(sock, code):
            """Receive and extract the next message and raise if the reply
               doesn't match the expected `code`.
            """
            line = sock.recv(1024).decode('ascii')
            recv_code, msg = line.split()[0:2]
            recv_code = int(recv_code)
            if code != recv_code:
                raise exception.ValidationError('Expected %d but received %d'
                                                % (code, recv_code))
            return msg

        sock = compute_sock
        expect(sock, self.VMAD_WELCOME)
        sock = ssl.wrap_socket(sock)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        cert = sock.getpeercert(binary_form=True) or bytes()
        h = hashlib.sha1()
        h.update(cert)
        if thumbprint != h.hexdigest():
            raise exception.ValidationError("Server thumbprint doesn't match")
        sock.sendall(
            ("%s %s\r\n" % (self.VMAD_USER_CMD, ticket)).encode('ascii'))
        expect(sock, self.VMAD_NEEDPASSWD)
        sock.sendall(
            ("%s %s\r\n" % (self.VMAD_PASS_CMD, ticket)).encode('ascii'))
        expect(sock, self.VMAD_LOGINOK)
        rand = os.urandom(12)
        rand_b = base64.b64encode(rand)
        rand_s = rand_b.decode('ascii')
        sock.sendall(
            ("%s %s\r\n" % (self.VMAD_THUMB_CMD, rand_s)).encode('ascii'))
        thumbprint2 = expect(sock, self.VMAD_OK)
        thumbprint2 = thumbprint2.replace(':', '').lower()
        sock.sendall(
            ("%s %s mks\r\n" % (self.VMAD_CONNECT_CMD, cfg_file))
            .encode('ascii'))
        expect(sock, self.VMAD_OK)
        sock2 = ssl.wrap_socket(sock)
        cert2 = sock2.getpeercert(binary_form=True) or bytes()
        h = hashlib.sha1()
        h.update(cert2)
        if thumbprint2 != h.hexdigest():
            raise exception.ValidationError("Second thumbprint doesn't match")
        sock2.sendall(rand_b)
        return sock2
