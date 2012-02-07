# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 University of Southern California
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
#

from nova.virt.baremetal import tilera
from nova.virt.baremetal import fake
from nova.openstack.common import cfg
from nova import flags
from nova import exception

FLAGS = flags.FLAGS

global_opts = [
    cfg.StrOpt('baremetal_driver',
               default='tilera',
               help='Bare-metal driver runs on')
    ]

FLAGS.add_options(global_opts)


def get_baremetal_nodes():
    d = FLAGS.baremetal_driver
    if  d == 'tilera':
        return tilera.get_baremetal_nodes()
    elif d == 'fake':
        return fake.get_baremetal_nodes()
    else:
        raise exception.Error(_("Unknown baremetal driver %(d)s"))
