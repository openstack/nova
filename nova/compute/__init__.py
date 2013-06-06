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
import nova.exception
import nova.openstack.common.importutils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

_compute_opts = [
    oslo.config.cfg.StrOpt('compute_api_class',
                           default='nova.compute.api.API',
                           help='The full class name of the '
                                'compute API class to use (deprecated)'),
]
oslo.config.cfg.CONF.register_opts(_compute_opts)

oslo.config.cfg.CONF.import_opt('enable',
                            'nova.cells.opts',
                            group='cells')

oslo.config.cfg.CONF.import_opt('cell_type',
                            'nova.cells.opts',
                            group='cells')

COMPUTE_API = 'nova.compute.api.API'
COMPUTE_CELL_API = 'nova.compute.cells_api.ComputeCellsAPI'


def get_compute_api_class_name():
    """
    Returns the name of compute API class.
    """
    if not oslo.config.cfg.CONF.cells.enable:
        return COMPUTE_API

    cell_type = oslo.config.cfg.CONF.cells.cell_type
    # If cell is enabled and cell_type option is not set (and thus get the
    # default value None), use the deprecated compute_api_class option.
    if cell_type is None:
        compute_api_class_name = oslo.config.cfg.CONF.compute_api_class
        LOG.deprecated(_("The compute_api_class is now deprecated and "
                         "will be removed in next release. Please set the"
                         " cell_type option to api or compute"))
    # If cell is enabled and this cell is an API-cell, use cell specific
    # computeAPI.
    elif cell_type == 'api':
        compute_api_class_name = COMPUTE_CELL_API
    # If cell is enabled and this cell is a COMPUTE-cell, use normal
    # computeAPI.
    elif cell_type == 'compute':
        compute_api_class_name = COMPUTE_API
    # Otherwise, raise exception for invalid cell_type
    else:
        msg = _("cell_type must be configured as 'api' or 'compute'")
        raise nova.exception.InvalidInput(reason=msg)
    return compute_api_class_name


def API(*args, **kwargs):
    importutils = nova.openstack.common.importutils
    class_name = get_compute_api_class_name()
    return importutils.import_object(class_name, *args, **kwargs)


def HostAPI(*args, **kwargs):
    """
    Returns the 'HostAPI' class from the same module as the configured compute
    api
    """
    importutils = nova.openstack.common.importutils
    compute_api_class_name = get_compute_api_class_name()
    compute_api_class = importutils.import_class(compute_api_class_name)
    class_name = compute_api_class.__module__ + ".HostAPI"
    return importutils.import_object(class_name, *args, **kwargs)


def InstanceActionAPI(*args, **kwargs):
    """
    Returns the 'InstanceActionAPI' class from the same module as the
    configured compute api.
    """
    importutils = nova.openstack.common.importutils
    compute_api_class_name = get_compute_api_class_name()
    compute_api_class = importutils.import_class(compute_api_class_name)
    class_name = compute_api_class.__module__ + ".InstanceActionAPI"
    return importutils.import_object(class_name, *args, **kwargs)
