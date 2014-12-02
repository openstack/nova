# Copyright (c) 2012 OpenStack Foundation.
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

from __future__ import print_function

import copy
import errno
import gc
import os
import pprint
import socket
import sys
import traceback

import eventlet
import eventlet.backdoor
import greenlet
from oslo.config import cfg

from nova.openstack.common._i18n import _LI
from nova.openstack.common import log as logging

help_for_backdoor_port = (
    "Acceptable values are 0, <port>, and <start>:<end>, where 0 results "
    "in listening on a random tcp port number; <port> results in listening "
    "on the specified port number (and not enabling backdoor if that port "
    "is in use); and <start>:<end> results in listening on the smallest "
    "unused port number within the specified range of port numbers.  The "
    "chosen port is displayed in the service's log file.")
eventlet_backdoor_opts = [
    cfg.StrOpt('backdoor_port',
               help="Enable eventlet backdoor.  %s" % help_for_backdoor_port)
]

CONF = cfg.CONF
CONF.register_opts(eventlet_backdoor_opts)
LOG = logging.getLogger(__name__)


def list_opts():
    """Entry point for oslo.config-generator.
    """
    return [(None, copy.deepcopy(eventlet_backdoor_opts))]


class EventletBackdoorConfigValueError(Exception):
    def __init__(self, port_range, help_msg, ex):
        msg = ('Invalid backdoor_port configuration %(range)s: %(ex)s. '
               '%(help)s' %
               {'range': port_range, 'ex': ex, 'help': help_msg})
        super(EventletBackdoorConfigValueError, self).__init__(msg)
        self.port_range = port_range


def _dont_use_this():
    print("Don't use this, just disconnect instead")


def _find_objects(t):
    return [o for o in gc.get_objects() if isinstance(o, t)]


def _print_greenthreads():
    for i, gt in enumerate(_find_objects(greenlet.greenlet)):
        print(i, gt)
        traceback.print_stack(gt.gr_frame)
        print()


def _print_nativethreads():
    for threadId, stack in sys._current_frames().items():
        print(threadId)
        traceback.print_stack(stack)
        print()


def _parse_port_range(port_range):
    if ':' not in port_range:
        start, end = port_range, port_range
    else:
        start, end = port_range.split(':', 1)
    try:
        start, end = int(start), int(end)
        if end < start:
            raise ValueError
        return start, end
    except ValueError as ex:
        raise EventletBackdoorConfigValueError(port_range, ex,
                                               help_for_backdoor_port)


def _listen(host, start_port, end_port, listen_func):
    try_port = start_port
    while True:
        try:
            return listen_func((host, try_port))
        except socket.error as exc:
            if (exc.errno != errno.EADDRINUSE or
               try_port >= end_port):
                raise
            try_port += 1


def initialize_if_enabled():
    backdoor_locals = {
        'exit': _dont_use_this,      # So we don't exit the entire process
        'quit': _dont_use_this,      # So we don't exit the entire process
        'fo': _find_objects,
        'pgt': _print_greenthreads,
        'pnt': _print_nativethreads,
    }

    if CONF.backdoor_port is None:
        return None

    start_port, end_port = _parse_port_range(str(CONF.backdoor_port))

    # NOTE(johannes): The standard sys.displayhook will print the value of
    # the last expression and set it to __builtin__._, which overwrites
    # the __builtin__._ that gettext sets. Let's switch to using pprint
    # since it won't interact poorly with gettext, and it's easier to
    # read the output too.
    def displayhook(val):
        if val is not None:
            pprint.pprint(val)
    sys.displayhook = displayhook

    sock = _listen('localhost', start_port, end_port, eventlet.listen)

    # In the case of backdoor port being zero, a port number is assigned by
    # listen().  In any case, pull the port number out here.
    port = sock.getsockname()[1]
    LOG.info(
        _LI('Eventlet backdoor listening on %(port)s for process %(pid)d') %
        {'port': port, 'pid': os.getpid()}
    )
    eventlet.spawn_n(eventlet.backdoor.backdoor_server, sock,
                     locals=backdoor_locals)
    return port
