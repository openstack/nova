# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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

import os
import sys

from oslo_config import cfg

ALL_OPTS = [
    cfg.StrOpt('pybasedir',
        default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                             '../../')),
        help="""
The directory where the Nova python modules are installed.

This directory is used to store template files for networking and remote
console access. It is also the default path for other config options which
need to persist Nova internal data. It is very unlikely that you need to
change this option from its default value.

Possible values:

* The full path to a directory.

Related options:

* ``state_path``
"""),
    cfg.StrOpt('bindir',
        default=os.path.join(sys.prefix, 'local', 'bin'),
        help="""
The directory where the Nova binaries are installed.

This option is only relevant if the networking capabilities from Nova are
used (see services below). Nova's networking capabilities are targeted to
be fully replaced by Neutron in the future. It is very unlikely that you need
to change this option from its default value.

Possible values:

* The full path to a directory.
"""),

    cfg.StrOpt('state_path',
        default='$pybasedir',
        help="""
The top-level directory for maintaining Nova's state.

This directory is used to store Nova's internal state. It is used by a
variety of other config options which derive from this. In some scenarios
(for example migrations) it makes sense to use a storage location which is
shared between multiple compute hosts (for example via NFS). Unless the
option ``instances_path`` gets overwritten, this directory can grow very
large.

Possible values:

* The full path to a directory. Defaults to value provided in ``pybasedir``.
"""),
]


def basedir_def(*args):
    """Return an uninterpolated path relative to $pybasedir."""
    return os.path.join('$pybasedir', *args)


def bindir_def(*args):
    """Return an uninterpolated path relative to $bindir."""
    return os.path.join('$bindir', *args)


def state_path_def(*args):
    """Return an uninterpolated path relative to $state_path."""
    return os.path.join('$state_path', *args)


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
