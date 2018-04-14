# Copyright 2018 Michael Still and Aptira
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

"""
xenapi specific routines.
"""

from oslo_concurrency import processutils

import nova.privsep


@nova.privsep.sys_admin_pctxt.entrypoint
def xenstore_read(path):
    return processutils.execute('xenstore-read', path)


@nova.privsep.sys_admin_pctxt.entrypoint
def block_copy(src_path, dst_path, block_size, num_blocks):
    processutils.execute('dd',
                         'if=%s' % src_path,
                         'of=%s' % dst_path,
                         'bs=%d' % block_size,
                         'count=%d' % num_blocks,
                         'iflag=direct,sync',
                         'oflag=direct,sync')
