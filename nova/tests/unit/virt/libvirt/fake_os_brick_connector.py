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


def get_connector_properties(root_helper, my_ip, multipath, enforce_multipath,
                             host=None):
    """Fake os-brick."""

    props = {}
    props['ip'] = my_ip
    props['host'] = host
    iscsi = ISCSIConnector('')
    props['initiator'] = iscsi.get_initiator()
    props['wwpns'] = ['100010604b019419']
    props['wwnns'] = ['200010604b019419']
    props['multipath'] = multipath
    props['platform'] = 'x86_64'
    props['os_type'] = 'linux2'
    return props


class ISCSIConnector(object):
    """Mimick the iSCSI connector."""

    def __init__(self, root_helper, driver=None,
                 execute=None, use_multipath=False,
                 device_scan_attempts=3,
                 *args, **kwargs):
        self.root_herlp = root_helper,
        self.execute = execute

    def get_initiator(self):
        return "fake_iscsi.iqn"
