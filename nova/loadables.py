# Copyright (c) 2011-2012 OpenStack Foundation
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
Generic Loadable class support.

Meant to be used by such things as scheduler filters and weights where we
want to load modules from certain directories and find certain types of
classes within those modules.  Note that this is quite different than
generic plugins and the pluginmanager code that exists elsewhere.

Usage:

Create a directory with an __init__.py with code such as:

class SomeLoadableClass(object):
    pass


class MyLoader(nova.loadables.BaseLoader)
    def __init__(self):
        super(MyLoader, self).__init__(SomeLoadableClass)

If you create modules in the same directory and subclass SomeLoadableClass
within them, MyLoader().get_all_classes() will return a list
of such classes.
"""

import inspect
import os
import sys

from oslo_utils import importutils

from nova import exception


class BaseLoader(object):
    def __init__(self, loadable_cls_type):
        mod = sys.modules[self.__class__.__module__]
        self.path = os.path.abspath(mod.__path__[0])
        self.package = mod.__package__
        self.loadable_cls_type = loadable_cls_type

    def _is_correct_class(self, obj):
        """Return whether an object is a class of the correct type and
        is not prefixed with an underscore.
        """
        return (inspect.isclass(obj) and
                (not obj.__name__.startswith('_')) and
                issubclass(obj, self.loadable_cls_type))

    def _get_classes_from_module(self, module_name):
        """Get the classes from a module that match the type we want."""
        classes = []
        module = importutils.import_module(module_name)
        for obj_name in dir(module):
            # Skip objects that are meant to be private.
            if obj_name.startswith('_'):
                continue
            itm = getattr(module, obj_name)
            if self._is_correct_class(itm):
                classes.append(itm)
        return classes

    def get_all_classes(self):
        """Get the classes of the type we want from all modules found
        in the directory that defines this class.
        """
        classes = []
        for dirpath, dirnames, filenames in os.walk(self.path):
            relpath = os.path.relpath(dirpath, self.path)
            if relpath == '.':
                relpkg = ''
            else:
                relpkg = '.%s' % '.'.join(relpath.split(os.sep))
            for fname in filenames:
                root, ext = os.path.splitext(fname)
                if ext != '.py' or root == '__init__':
                    continue
                module_name = "%s%s.%s" % (self.package, relpkg, root)
                mod_classes = self._get_classes_from_module(module_name)
                classes.extend(mod_classes)
        return classes

    def get_matching_classes(self, loadable_class_names):
        """Get loadable classes from a list of names.  Each name can be
        a full module path or the full path to a method that returns
        classes to use.  The latter behavior is useful to specify a method
        that returns a list of classes to use in a default case.
        """
        classes = []
        for cls_name in loadable_class_names:
            obj = importutils.import_class(cls_name)
            if self._is_correct_class(obj):
                classes.append(obj)
            elif inspect.isfunction(obj):
                # Get list of classes from a function
                for cls in obj():
                    classes.append(cls)
            else:
                error_str = 'Not a class of the correct type'
                raise exception.ClassNotFound(class_name=cls_name,
                                              exception=error_str)
        return classes
