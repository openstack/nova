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

import abc


class SecurityProxy(metaclass=abc.ABCMeta):
    """A console security Proxy Helper

    Console security proxy helpers should subclass
    this class and implement a generic `connect`
    for the particular protocol being used.

    Security drivers can then subclass the
    protocol-specific helper class.
    """

    @abc.abstractmethod
    def connect(self, tenant_sock, compute_sock):
        """Initiate the console connection

        This method performs the protocol specific
        negotiation, and returns the socket-like
        object to use to communicate with the server
        securely.

        :param tenant_sock: socket connected to the remote tenant user
        :param compute_sock: socket connected to the compute node instance

        :returns: a new compute_sock for the instance
        """
        pass
