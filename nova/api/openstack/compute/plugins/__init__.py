# Copyright 2013 IBM Corp.
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


from nova import exception
from nova.i18n import _LE
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class LoadedExtensionInfo(object):
    """Keep track of all loaded API extensions."""

    def __init__(self):
        self.extensions = {}

    def register_extension(self, ext):
        if not self._check_extension(ext):
            return False

        alias = ext.alias

        if alias in self.extensions:
            raise exception.NovaException("Found duplicate extension: %s"
                                          % alias)
        self.extensions[alias] = ext
        return True

    def _check_extension(self, extension):
        """Checks for required methods in extension objects."""
        try:
            extension.is_valid()
        except AttributeError as ex:
            LOG.exception(_LE("Exception loading extension: %s"), ex)
            return False

        return True

    def get_extensions(self):
        return self.extensions
