# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
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

import oslo.config.cfg

# Importing full names to not pollute the namespace and cause possible
# collisions with use of 'from nova.compute import <foo>' elsewhere.
import nova.openstack.common.importutils

_compute_opts = [
    oslo.config.cfg.StrOpt('compute_api_class',
                           default='nova.compute.api.API',
                           help='The full class name of the '
                                'compute API class to use'),
]

oslo.config.cfg.CONF.register_opts(_compute_opts)


def API(*args, **kwargs):
    importutils = nova.openstack.common.importutils
    class_name = oslo.config.cfg.CONF.compute_api_class
    return importutils.import_object(class_name, *args, **kwargs)


def HostAPI(*args, **kwargs):
    """
    Returns the 'HostAPI' class from the same module as the configured compute
    api
    """
    importutils = nova.openstack.common.importutils
    compute_api_class_name = oslo.config.cfg.CONF.compute_api_class
    compute_api_class = importutils.import_class(compute_api_class_name)
    class_name = compute_api_class.__module__ + ".HostAPI"
    return importutils.import_object(class_name, *args, **kwargs)


def InstanceActionAPI(*args, **kwargs):
    """
    Returns the 'InstanceActionAPI' class from the same module as the
    configured compute api.
    """
    importutils = nova.openstack.common.importutils
    compute_api_class_name = oslo.config.cfg.CONF.compute_api_class
    compute_api_class = importutils.import_class(compute_api_class_name)
    class_name = compute_api_class.__module__ + ".InstanceActionAPI"
    return importutils.import_object(class_name, *args, **kwargs)
