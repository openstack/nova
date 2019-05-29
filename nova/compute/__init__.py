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

from oslo_utils import importutils

# TODO(stephenfin): Remove this nonsense
CELL_TYPE_TO_CLS_NAME = {None: 'nova.compute.api.API'}


def _get_compute_api_class_name():
    """Returns the name of compute API class."""
    return CELL_TYPE_TO_CLS_NAME[None]


def API(*args, **kwargs):
    class_name = _get_compute_api_class_name()
    return importutils.import_object(class_name, *args, **kwargs)


def HostAPI(*args, **kwargs):
    """Returns the 'HostAPI' class from the same module as the configured
    compute api
    """
    compute_api_class_name = _get_compute_api_class_name()
    compute_api_class = importutils.import_class(compute_api_class_name)
    class_name = compute_api_class.__module__ + ".HostAPI"
    return importutils.import_object(class_name, *args, **kwargs)


def InstanceActionAPI(*args, **kwargs):
    """Returns the 'InstanceActionAPI' class from the same module as the
    configured compute api.
    """
    compute_api_class_name = _get_compute_api_class_name()
    compute_api_class = importutils.import_class(compute_api_class_name)
    class_name = compute_api_class.__module__ + ".InstanceActionAPI"
    return importutils.import_object(class_name, *args, **kwargs)
