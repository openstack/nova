# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import imp
import os
import sys


class ExtensionManager(object):

    def __init__(self, path):

        self.path = path
        self.extensions = []
        self._load_extensions()

    def get_resources(self):
        """
        returns a list of ExtensionResource objects
        """
        resources = []
        for ext in self.extensions:
            resources.append(ext.get_resources())
        return resources

    def _load_extensions(self):
        if not os.path.exists(self.path):
            return

        for f in os.listdir(self.path):
            mod_name, file_ext = os.path.splitext(os.path.split(f)[-1])
            ext_path = os.path.join(self.path, f)
            if file_ext.lower() == '.py':
                mod = imp.load_source(mod_name, ext_path)
                self.extensions.append(getattr(mod, 'get_extension')())


class ExtensionResource(object):
    """
    Example ExtensionResource object. All ExtensionResource objects should
    adhere to this interface.
    """

    def add_routes(self, mapper):
        pass
