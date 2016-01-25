# Copyright 2015 OpenStack Foundation
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
This is the single point of entry to generate the sample configuration
file for Nova. It collects all the necessary info from the other modules
in this package. It is assumed that:

* every other module in this package has a 'list_opts' function which
  return a dict where
  * the keys are strings which are the group names
  * the value of each key is a list of config options for that group
* the nova.conf package doesn't have further packages with config options
* this module is only used in the context of sample file generation
"""

import collections
import importlib
import os
import pkgutil

LIST_OPTS_FUNC_NAME = "list_opts"


def _tupleize(dct):
    """Take the dict of options and convert to the 2-tuple format."""
    return [(key, val) for key, val in dct.items()]


def list_opts():
    opts = collections.defaultdict(list)
    module_names = _list_module_names()
    imported_modules = _import_modules(module_names)
    _append_config_options(imported_modules, opts)
    return _tupleize(opts)


def _list_module_names():
    module_names = []
    package_path = os.path.dirname(os.path.abspath(__file__))
    for _, modname, ispkg in pkgutil.iter_modules(path=[package_path]):
        if modname == "opts" or ispkg:
            continue
        else:
            module_names.append(modname)
    return module_names


def _import_modules(module_names):
    imported_modules = []
    for modname in module_names:
        mod = importlib.import_module("nova.conf." + modname)
        if not hasattr(mod, LIST_OPTS_FUNC_NAME):
            msg = "The module 'nova.conf.%s' should have a '%s' "\
                  "function which returns the config options." % \
                  (modname, LIST_OPTS_FUNC_NAME)
            raise Exception(msg)
        else:
            imported_modules.append(mod)
    return imported_modules


def _process_old_opts(configs):
    """Convert old-style 2-tuple configs to dicts."""
    if isinstance(configs, tuple):
        configs = [configs]
    return {label: options for label, options in configs}


def _append_config_options(imported_modules, config_options):
    for mod in imported_modules:
        configs = mod.list_opts()
        # TODO(markus_z): Remove this compatibility shim once all list_opts()
        # functions have been updated to return dicts.
        if not isinstance(configs, dict):
            configs = _process_old_opts(configs)
        for key, val in configs.items():
            config_options[key].extend(val)
