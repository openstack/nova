# Copyright 2013 NEC Corporation.  All rights reserved.
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
Request Body validating middleware.

"""

import functools

from nova.api.openstack import api_version_request as api_version
from nova.api.validation import validators


def schema(request_body_schema, min_version=None, max_version=None):
    """Register a schema to validate request body.

    Registered schema will be used for validating request body just before
    API method executing.

    :argument dict request_body_schema: a schema to validate request body

    """
    schema_validator = validators._SchemaValidator(request_body_schema)

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            min_ver = api_version.APIVersionRequest(min_version)
            max_ver = api_version.APIVersionRequest(max_version)

            # The request object is always the second argument.
            # However numerous unittests pass in the request object
            # via kwargs instead so we handle that as well.
            # TODO(cyeoh): cleanup unittests so we don't have to
            # to do this
            if 'req' in kwargs:
                ver = kwargs['req'].api_version_request
            else:
                ver = args[1].api_version_request
            if ver.matches(min_ver, max_ver):
                # Only validate against the schema if it lies within
                # the version range specified. Note that if both min
                # and max are not specified the validator will always
                # be run.
                schema_validator.validate(kwargs['body'])

            return func(*args, **kwargs)
        return wrapper

    return add_validator
