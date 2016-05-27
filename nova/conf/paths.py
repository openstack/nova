# needs:fix_opt_description
# needs:check_deprecation_status
# needs:check_opt_group_and_type
# needs:fix_opt_description_indentation
# needs:fix_opt_registration_consistency


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

path_opts = [
    cfg.StrOpt('pybasedir',
               default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                    '../../')),
               help='Directory where the nova python module is installed'),
    cfg.StrOpt('bindir',
               default=os.path.join(sys.prefix, 'local', 'bin'),
               help='Directory where nova binaries are installed'),
    cfg.StrOpt('state_path',
               default='$pybasedir',
               help="Top-level directory for maintaining nova's state"),
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


# TODO(markus_z): This needs to be removed in a new patch. No one uses this.
def basedir_rel(*args):
    """Return a path relative to $pybasedir."""
    return os.path.join(cfg.CONF.pybasedir, *args)


# TODO(markus_z): This needs to be removed in a new patch. No one uses this.
def bindir_rel(*args):
    """Return a path relative to $bindir."""
    return os.path.join(cfg.CONF.bindir, *args)


# TODO(markus_z): This needs to be removed in a new patch. No one uses this.
def state_path_rel(*args):
    """Return a path relative to $state_path."""
    return os.path.join(cfg.CONF.state_path, *args)


def register_opts(conf):
    conf.register_opts(path_opts)


def list_opts():
    return {"DEFAULT": path_opts}
