# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils

LOG = logging.getLogger('nova.virt.conn_common')
FLAGS = flags.FLAGS

flags.DEFINE_string('injected_network_template',
                    utils.abspath('virt/interfaces.template'),
                    'Template file for injected network')


def get_injectables(inst):
    key = str(inst['key_data'])
    net = None
    network_ref = db.network_get_by_instance(context.get_admin_context(),
                                             inst['id'])
    if network_ref['injected']:
        admin_context = context.get_admin_context()
        address = db.instance_get_fixed_address(admin_context, inst['id'])
        ra_server = network_ref['ra_server']
        if not ra_server:
            ra_server = "fd00::"
        with open(FLAGS.injected_network_template) as f:
            net = f.read() % {'address': address,
                              'netmask': network_ref['netmask'],
                              'gateway': network_ref['gateway'],
                              'broadcast': network_ref['broadcast'],
                              'dns': network_ref['dns'],
                              'ra_server': ra_server}

    return key, net
