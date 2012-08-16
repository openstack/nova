# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC.
# Administrator of the National Aeronautics and Space Administration.
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

import gc
import pprint
import sys
import traceback

import eventlet
import eventlet.backdoor
import greenlet

from nova import flags
from nova.openstack.common import cfg

eventlet_backdoor_opts = [
    cfg.IntOpt('backdoor_port',
               default=None,
               help='port for eventlet backdoor to listen')
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(eventlet_backdoor_opts)


def dont_use_this():
    print "Don't use this, just disconnect instead"


def find_objects(t):
    return filter(lambda o: isinstance(o, t), gc.get_objects())


def print_greenthreads():
    for i, gt in enumerate(find_objects(greenlet.greenlet)):
        print i, gt
        traceback.print_stack(gt.gr_frame)
        print


backdoor_locals = {
    'exit': dont_use_this,      # So we don't exit the entire process
    'quit': dont_use_this,      # So we don't exit the entire process
    'fo': find_objects,
    'pgt': print_greenthreads,
}


def initialize_if_enabled():
    if FLAGS.backdoor_port is None:
        return

    # NOTE(johannes): The standard sys.displayhook will print the value of
    # the last expression and set it to __builtin__._, which overwrites
    # the __builtin__._ that gettext sets. Let's switch to using pprint
    # since it won't interact poorly with gettext, and it's easier to
    # read the output too.
    def displayhook(val):
        if val is not None:
            pprint.pprint(val)
    sys.displayhook = displayhook

    eventlet.spawn(eventlet.backdoor.backdoor_server,
                   eventlet.listen(('localhost', FLAGS.backdoor_port)),
                   locals=backdoor_locals)
