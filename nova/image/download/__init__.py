# Copyright 2013 Red Hat, Inc.
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

from oslo_log import log as logging
import stevedore.driver
import stevedore.extension

from nova.i18n import _LE

LOG = logging.getLogger(__name__)


def load_transfer_modules():

    module_dictionary = {}

    ex = stevedore.extension.ExtensionManager('nova.image.download.modules')
    for module_name in ex.names():
        mgr = stevedore.driver.DriverManager(
            namespace='nova.image.download.modules',
            name=module_name,
            invoke_on_load=False)

        schemes_list = mgr.driver.get_schemes()
        for scheme in schemes_list:
            if scheme in module_dictionary:
                LOG.error(_LE('%(scheme)s is registered as a module twice. '
                              '%(module_name)s is not being used.'),
                          {'scheme': scheme,
                           'module_name': module_name})
            else:
                module_dictionary[scheme] = mgr.driver

    return module_dictionary
