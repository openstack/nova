# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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

"""Contrib contains extensions that are shipped with nova.

It can't be called 'extensions' because that causes namespacing problems.

"""

import os

from nova import exception
from nova import log as logging
from nova import utils


LOG = logging.getLogger('nova.api.openstack.v2.contrib')


def standard_extensions(ext_mgr):
    """Registers all standard API extensions."""

    # Walk through all the modules in our directory...
    our_dir = __path__[0]
    for dirpath, dirnames, filenames in os.walk(our_dir):
        # Compute the relative package name from the dirpath
        relpath = os.path.relpath(dirpath, our_dir)
        if relpath == '.':
            relpkg = ''
        else:
            relpkg = '.%s' % '.'.join(relpath.split(os.sep))

        # Now, consider each file in turn, only considering .py files
        for fname in filenames:
            root, ext = os.path.splitext(fname)

            # Skip __init__ and anything that's not .py
            if ext != '.py' or root == '__init__':
                continue

            # Try loading it
            classname = ("%s%s.%s.%s%s" %
                         (__package__, relpkg, root,
                          root[0].upper(), root[1:]))
            try:
                ext_mgr.load_extension(classname)
            except Exception as exc:
                LOG.warn(_('Failed to load extension %(classname)s: '
                           '%(exc)s') % locals())

        # Now, let's consider any subdirectories we may have...
        subdirs = []
        for dname in dirnames:
            # Skip it if it does not have __init__.py
            if not os.path.exists(os.path.join(dirpath, dname,
                                               '__init__.py')):
                continue

            # If it has extension(), delegate...
            ext_name = ("%s%s.%s.extension" %
                        (__package__, relpkg, dname))
            try:
                ext = utils.import_class(ext_name)
            except exception.ClassNotFound:
                # extension() doesn't exist on it, so we'll explore
                # the directory for ourselves
                subdirs.append(dname)
            else:
                try:
                    ext(ext_mgr)
                except Exception as exc:
                    LOG.warn(_('Failed to load extension %(ext_name)s: '
                               '%(exc)s') % locals())

        # Update the list of directories we'll explore...
        dirnames[:] = subdirs
