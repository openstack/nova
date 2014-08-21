# Copyright 2011 Cloudscaling, Inc.
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

import base64

import rfc3986
import six

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def validate_str(max_length=None):

    def _do(val):
        if not isinstance(val, six.string_types):
            return False
        if max_length and len(val) > max_length:
            return False
        return True

    return _do


def validate_int(max_value=None):

    def _do(val):
        if not isinstance(val, int):
            return False
        if max_value and val > max_value:
            return False
        return True

    return _do


def validate_url_path(val):
    """True if val is matched by the path component grammar in rfc3986."""

    if not validate_str()(val):
        return False

    uri = rfc3986.URIReference(None, None, val, None, None)

    return uri.path_is_valid() and val.startswith('/')


def validate_image_path(val):
    if not validate_str()(val):
        return False

    bucket_name = val.split('/')[0]
    manifest_path = val[len(bucket_name) + 1:]
    if not len(bucket_name) or not len(manifest_path):
        return False

    if val[0] == '/':
        return False

    # make sure the image path if rfc3986 compliant
    # prepend '/' to make input validate
    if not validate_url_path('/' + val):
        return False

    return True


def validate_user_data(user_data):
    """Check if the user_data is encoded properly."""
    try:
        user_data = base64.b64decode(user_data)
    except TypeError:
        return False
    return True


def validate(args, validator):
    """Validate values of args against validators in validator.

    :param args:      Dict of values to be validated.
    :param validator: A dict where the keys map to keys in args
                      and the values are validators.
                      Applies each validator to ``args[key]``
    :returns: True if validation succeeds. Otherwise False.

    A validator should be a callable which accepts 1 argument and which
    returns True if the argument passes validation. False otherwise.
    A validator should not raise an exception to indicate validity of the
    argument.

    Only validates keys which show up in both args and validator.

    """

    for key in validator:
        if key not in args:
            continue

        f = validator[key]
        assert callable(f)

        if not f(args[key]):
            LOG.debug("%(key)s with value %(value)s failed"
                      " validator %(name)s",
                      {'key': key, 'value': args[key], 'name': f.__name__})
            return False
    return True
