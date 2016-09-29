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

# possible ops
CREATE = 'create'
UPDATE = 'update'
REBUILD = 'rebuild'
RESIZE = 'resize'


def disk_config_from_api(value):
    if value == 'AUTO':
        return True
    elif value == 'MANUAL':
        return False
    else:
        msg = _("%s must be either 'MANUAL' or 'AUTO'.") % API_DISK_CONFIG
        raise exc.HTTPBadRequest(explanation=msg)


def get_injected_files(personality):
    """Create a list of injected files from the personality attribute.

    At this time, injected_files must be formatted as a list of
    (file_path, file_content) pairs for compatibility with the
    underlying compute service.
    """
    injected_files = []
    for item in personality:
        injected_files.append((item['path'], item['contents']))
    return injected_files


def translate_attributes(op, server_dict, operation_kwargs):
    """Translate REST attributes on create to server object kwargs.

    Our REST API is relatively fixed, but internal representations
    change over time, this is a translator for inbound REST request
    attributes that modifies the server dict that we get and adds
    appropriate attributes to ``operation_kwargs`` that will be passed
    down to instance objects later.

    It's done in a common function as this is used for create / resize
    / rebuild / update

    The ``op`` is the operation that we are transforming, because
    there are times when we translate differently for different
    operations. (Yes, it's a little nuts, but legacy... )

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
    if 'preserve_ephemeral' in server_dict and op == REBUILD:
        preserve = strutils.bool_from_string(
            server_dict.pop('preserve_ephemeral'), strict=True)
        operation_kwargs['preserve_ephemeral'] = preserve

    # yes, we use different kwargs, this goes all the way back to
    # commit cebc98176926f57016a508d5c59b11f55dfcf2b3.
    if 'personality' in server_dict:
        if op == REBUILD:
            operation_kwargs['files_to_inject'] = get_injected_files(
                server_dict.pop('personality'))
    # NOTE(sdague): the deprecated hooks infrastructure doesn't
    # function if injected files is not defined as a list. Once hooks
    # are removed, this should go back inside the personality
    # conditional above.
    if op == CREATE:
        operation_kwargs['injected_files'] = get_injected_files(
            server_dict.pop('personality', []))
