#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from oslo_log import log as logging

from nova.i18n import _LW

LOG = logging.getLogger(__name__)


def get_domain_info(libvirt, host, virt_dom):
    """Method virDomain.info (libvirt version < 1.2.11) is
    affected by a race condition. See bug #1372670 for more details.
    This method detects it to perform a retry.
    """
    def is_race(e):
        code = e.get_error_code()
        message = e.get_error_message()
        return (code == libvirt.VIR_ERR_OPERATION_FAILED and
                'cannot read cputime for domain' in message)

    try:
        return virt_dom.info()
    except libvirt.libvirtError as e:
        if not host.has_min_version((1, 2, 11)) and is_race(e):
            LOG.warning(_LW('Race detected in libvirt.virDomain.info, '
                         'trying one more time'))
            return virt_dom.info()
        raise
