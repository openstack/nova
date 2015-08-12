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


class Console(object):
    def __init__(self, host, port, internal_access_path=None):
        self.host = host
        self.port = port
        self.internal_access_path = internal_access_path

    def get_connection_info(self, token, access_url):
        """Returns an unreferenced dict with connection information."""

        ret = dict(self.__dict__)
        ret['token'] = token
        ret['access_url'] = access_url
        return ret


class ConsoleVNC(Console):
    pass


class ConsoleRDP(Console):
    pass


class ConsoleSpice(Console):
    def __init__(self, host, port, tlsPort, internal_access_path=None):
        super(ConsoleSpice, self).__init__(host, port, internal_access_path)
        self.tlsPort = tlsPort


class ConsoleSerial(Console):
    pass


class ConsoleMKS(Console):
    pass
