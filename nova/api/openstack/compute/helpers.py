# Copyright 2016 HPE, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from oslo_utils import strutils
from webob import exc

from nova.i18n import _

API_DISK_CONFIG = "OS-DCF:diskConfig"
API_ACCESS_V4 = "accessIPv4"
API_ACCESS_V6 = "accessIPv6"


def disk_config_from_api(value):
    if value == 'AUTO':
        return True
    elif value == 'MANUAL':
        return False
    else:
        msg = _("%s must be either 'MANUAL' or 'AUTO'.") % API_DISK_CONFIG
        raise exc.HTTPBadRequest(explanation=msg)


def translate_attributes(server_dict, operation_kwargs):
    """Translate REST attributes on create to server object kwargs.

    Our REST API is relatively fixed, but internal representations
    change over time, this is a translator for inbound REST request
    attributes that modifies the server dict that we get and adds
    appropriate attributes to ``operation_kwargs`` that will be passed
    down to instance objects later.

    It's done in a common function as this is used for create / resize
    / rebuild / update

    The ``server_dict`` is a representation of the server in
    question. During ``create`` and ``update`` operations this will
    actually be the ``server`` element of the request body.

    During actions, such as ``rebuild`` and ``resize`` this will be
    the attributes passed to the action object during the
    operation. This is equivalent to the ``server`` object.

    Not all operations support all attributes listed here. Which is
    why it's important to only set operation_kwargs if there is
    something to set. Input validation will ensure that we are only
    operating on appropriate attributes for each operation.
    """
    # Disk config
    auto_disk_config_raw = server_dict.pop(API_DISK_CONFIG, None)
    if auto_disk_config_raw is not None:
        auto_disk_config = disk_config_from_api(auto_disk_config_raw)
        operation_kwargs['auto_disk_config'] = auto_disk_config

    if API_ACCESS_V4 in server_dict:
        operation_kwargs['access_ip_v4'] = server_dict.pop(API_ACCESS_V4)
    if API_ACCESS_V6 in server_dict:
        operation_kwargs['access_ip_v6'] = server_dict.pop(API_ACCESS_V6)

    # This is only ever expected during rebuild operations, and only
    # does anything with Ironic driver. It also demonstrates the lack
    # of understanding of the word ephemeral.
    if 'preserve_ephemeral' in server_dict:
        preserve = strutils.bool_from_string(
            server_dict.pop('preserve_ephemeral'), strict=True)
        operation_kwargs['preserve_ephemeral'] = preserve
