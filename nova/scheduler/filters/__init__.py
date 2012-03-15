# Copyright (c) 2011 OpenStack, LLC.
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

"""
Scheduler host filters
"""

import os
import types

from nova import exception
from nova import utils


class BaseHostFilter(object):
    """Base class for host filters."""

    def host_passes(self, host_state, filter_properties):
        raise NotImplemented()

    def _full_name(self):
        """module.classname of the filter."""
        return "%s.%s" % (self.__module__, self.__class__.__name__)


def _is_filter_class(cls):
    """Return whether a class is a valid Host Filter class."""
    return type(cls) is types.TypeType and issubclass(cls, BaseHostFilter)


def _get_filter_classes_from_module(module_name):
    """Get all filter classes from a module."""
    classes = []
    module = utils.import_object(module_name)
    for obj_name in dir(module):
        itm = getattr(module, obj_name)
        if _is_filter_class(itm):
            classes.append(itm)
    return classes


def standard_filters():
    """Return a list of filter classes found in this directory."""
    classes = []
    filters_dir = __path__[0]
    for dirpath, dirnames, filenames in os.walk(filters_dir):
        relpath = os.path.relpath(dirpath, filters_dir)
        if relpath == '.':
            relpkg = ''
        else:
            relpkg = '.%s' % '.'.join(relpath.split(os.sep))
        for fname in filenames:
            root, ext = os.path.splitext(fname)
            if ext != '.py' or root == '__init__':
                continue
            module_name = "%s%s.%s" % (__package__, relpkg, root)
            mod_classes = _get_filter_classes_from_module(module_name)
            classes.extend(mod_classes)
    return classes


def get_filter_classes(filter_class_names):
    """Get filter classes from class names."""
    classes = []
    for cls_name in filter_class_names:
        obj = utils.import_class(cls_name)
        if _is_filter_class(obj):
            classes.append(obj)
        elif type(obj) is types.FunctionType:
            # Get list of classes from a function
            classes.extend(obj())
        else:
            raise exception.ClassNotFound(class_name=cls_name,
                    exception='Not a valid scheduler filter')
    return classes
