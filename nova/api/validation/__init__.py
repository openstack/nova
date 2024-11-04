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
import re
import typing as ty

from oslo_log import log as logging
from oslo_serialization import jsonutils
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import wsgi
from nova.api.validation import validators
import nova.conf
from nova import exception
from nova.i18n import _

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def validated(cls):
    cls._validated = True
    return cls


class Schemas:
    """A microversion-aware schema container.

    Allow definition and retrieval of schemas on a microversion-aware basis.
    """

    def __init__(self) -> None:
        self._schemas: list[
            tuple[
                dict[str, object],
                api_version_request.APIVersionRequest,
                api_version_request.APIVersionRequest,
            ]
        ] = []

    def add_schema(
        self,
        schema: tuple[dict[str, object]],
        min_version: ty.Optional[str],
        max_version: ty.Optional[str],
    ) -> None:
        # we'd like to use bisect.insort but that doesn't accept a 'key' arg
        # until Python 3.10, so we need to sort after insertion instead :(
        self._schemas.append(
            (
                schema,
                api_version_request.APIVersionRequest(min_version),
                api_version_request.APIVersionRequest(max_version),
            )
        )
        self._schemas.sort(key=lambda x: (x[1], x[2]))

        self.validate_schemas()

    def validate_schemas(self) -> None:
        """Ensure there are no overlapping schemas."""
        prev_max_version: ty.Optional[
            api_version_request.APIVersionRequest
        ] = None

        for schema, min_version, max_version in self._schemas:
            if prev_max_version:
                # it doesn't make sense to have multiple schemas if one of them
                # is unversioned (i.e. applies to everything)
                assert not prev_max_version.is_null()
                assert not min_version.is_null()
                # there should not be any gaps in schema coverage
                assert prev_max_version.ver_minor + 1 == min_version.ver_minor

            prev_max_version = max_version

    def __call__(self, req: wsgi.Request) -> ty.Optional[dict[str, object]]:
        ver = req.api_version_request

        for schema, min_version, max_version in self._schemas:
            if ver.matches(min_version, max_version):
                return schema

        # TODO(stephenfin): This should be an error in a future release
        return None


def _schema_validation_helper(schema, target, min_version, max_version,
                              args, kwargs, is_body=True):
    """A helper method to execute JSON-Schema Validation.

    This method checks the request version whether matches the specified max
    version and min_version. It also takes a care of legacy v2 request.

    If the version range matches the request, we validate the schema against
    the target and a failure will result in a ValidationError being raised.

    :param schema: A dict, the JSON-Schema is used to validate the target.
    :param target: A dict, the target is validated by the JSON-Schema.
    :param min_version: A string of two numerals. X.Y indicating the minimum
                        version of the JSON-Schema to validate against.
    :param max_version: A string of two numerals. X.Y indicating the maximum
                        version of the JSON-Schema to validate against.
    :param args: Positional arguments which passed into original method.
    :param kwargs: Keyword arguments which passed into original method.
    :param is_body: A boolean. Indicating whether the target is HTTP request
                    body or not.
    :returns: A boolean. `True` if and only if the version range matches the
              request AND the schema is successfully validated. `False` if the
              version range does not match the request and no validation is
              performed.
    :raises: ValidationError, when the validation fails.
    """
    min_ver = api_version_request.APIVersionRequest(min_version)
    max_ver = api_version_request.APIVersionRequest(max_version)

    # The request object is always the second argument.
    # However numerous unittests pass in the request object
    # via kwargs instead so we handle that as well.
    # TODO(cyeoh): cleanup unittests so we don't have to
    # to do this
    if 'req' in kwargs:
        ver = kwargs['req'].api_version_request
        legacy_v2 = kwargs['req'].is_legacy_v2()
    else:
        ver = args[1].api_version_request
        legacy_v2 = args[1].is_legacy_v2()

    if legacy_v2:
        # NOTE: For v2.0 compatible API, here should work like
        #    client  | schema min_version | schema
        # -----------+--------------------+--------
        #  legacy_v2 | None               | work
        #  legacy_v2 | 2.0                | work
        #  legacy_v2 | 2.1+               | don't
        if min_version is None or min_version == '2.0':
            schema_validator = validators._SchemaValidator(
                schema, legacy_v2, is_body)
            schema_validator.validate(target)
            return True
    elif ver.matches(min_ver, max_ver):
        # Only validate against the schema if it lies within
        # the version range specified. Note that if both min
        # and max are not specified the validator will always
        # be run.
        schema_validator = validators._SchemaValidator(
            schema, legacy_v2, is_body)
        schema_validator.validate(target)
        return True

    return False


# TODO(stephenfin): This decorator should take the five schemas we validate:
# request body, request query string, request headers, response body, and
# response headers. As things stand, we're going to need five separate
# decorators.
def schema(
    request_body_schema: ty.Dict[str, ty.Any],
    min_version: ty.Optional[str] = None,
    max_version: ty.Optional[str] = None,
):
    """Register a schema to validate request body.

    Registered schema will be used for validating request body just before
    API method executing.

    :param dict request_body_schema: a schema to validate request body
    :param dict response_body_schema: a schema to validate response body
    :param str min_version: Minimum API microversion that the schema applies to
    :param str max_version: Maximum API microversion that the schema applies to
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _schema_validation_helper(
                request_body_schema,
                kwargs['body'],
                min_version,
                max_version,
                args,
                kwargs
            )
            return func(*args, **kwargs)

        if not hasattr(wrapper, 'request_body_schemas'):
            wrapper.request_body_schemas = Schemas()

        wrapper.request_body_schemas.add_schema(
            request_body_schema, min_version, max_version
        )

        return wrapper

    return add_validator


def response_body_schema(
    response_body_schema: ty.Dict[str, ty.Any],
    min_version: ty.Optional[str] = None,
    max_version: ty.Optional[str] = None,
):
    """Register a schema to validate response body.

    Registered schema will be used for validating response body just after
    API method executing.

    :param dict response_body_schema: a schema to validate response body
    :param str min_version: Minimum API microversion that the schema applies to
    :param str max_version: Maximum API microversion that the schema applies to
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            response = func(*args, **kwargs)

            if CONF.api.response_validation == 'ignore':
                # don't waste our time checking anything if we're ignoring
                # schema errors
                return response

            # NOTE(stephenfin): If our response is an object, we need to
            # serializer and deserialize to convert e.g. date-time to strings
            if isinstance(response, wsgi.ResponseObject):
                serializer = wsgi.JSONDictSerializer()
                _body = serializer.serialize(response.obj)
            # TODO(stephenfin): We should replace all instances of this with
            # wsgi.ResponseObject
            elif isinstance(response, webob.Response):
                _body = response.body
            else:
                serializer = wsgi.JSONDictSerializer()
                _body = serializer.serialize(response)

            if _body == b'':
                body = None
            else:
                body = jsonutils.loads(_body)

            try:
                _schema_validation_helper(
                    response_body_schema,
                    body,
                    min_version,
                    max_version,
                    args,
                    kwargs
                )
            except exception.ValidationError:
                if CONF.api.response_validation == 'warn':
                    LOG.exception('Schema failed to validate')
                else:
                    raise
            return response

        if not hasattr(wrapper, 'response_body_schemas'):
            wrapper.response_body_schemas = Schemas()

        wrapper.response_body_schemas.add_schema(
            response_body_schema, min_version, max_version
        )

        return wrapper

    return add_validator


def _strip_additional_query_parameters(schema, req):
    """Strip the additional properties from the req.GET.

    This helper method assumes the JSON-Schema is only described as a dict
    without nesting. This method should be called after query parameters pass
    the JSON-Schema validation. It also means this method only can be called
    after _schema_validation_helper return `True`.
    """
    additional_properties = schema.get('additionalProperties', True)
    pattern_regexes = []

    patterns = schema.get('patternProperties', None)
    if patterns:
        for regex in patterns:
            pattern_regexes.append(re.compile(regex))

    if additional_properties:
        # `req.GET.keys` will return duplicated keys for multiple values
        # parameters. To get rid of duplicated keys, convert it to set.
        for param in set(req.GET.keys()):
            if param not in schema['properties'].keys():
                # keys that can match the patternProperties will be
                # retained and handle latter.
                if not (list(regex for regex in pattern_regexes if
                             regex.match(param))):
                    del req.GET[param]


def query_schema(request_query_schema, min_version=None,
                 max_version=None):
    """Register a schema to validate request query parameters.

    Registered schema will be used for validating request query params just
    before API method executing.

    :param request_query_schema: A dict, the JSON-Schema for validating the
                                query parameters.
    :param min_version: A string of two numerals. X.Y indicating the minimum
                        version of the JSON-Schema to validate against.
    :param max_version: A string of two numerals. X.Y indicating the maximum
                        version of the JSON-Schema against to.
    """

    def add_validator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # The request object is always the second argument.
            # However numerous unittests pass in the request object
            # via kwargs instead so we handle that as well.
            # TODO(cyeoh): cleanup unittests so we don't have to
            # to do this
            if 'req' in kwargs:
                req = kwargs['req']
            else:
                req = args[1]

            # NOTE(Kevin_Zheng): The webob package throws UnicodeError when
            # param cannot be decoded. Catch this and raise HTTP 400.

            try:
                query_dict = req.GET.dict_of_lists()
            except UnicodeDecodeError:
                msg = _('Query string is not UTF-8 encoded')
                raise exception.ValidationError(msg)

            if _schema_validation_helper(request_query_schema,
                                         query_dict,
                                         min_version, max_version,
                                         args, kwargs, is_body=False):
                # NOTE(alex_xu): The additional query parameters were stripped
                # out when `additionalProperties=True`. This is for backward
                # compatible with v2.1 API and legacy v2 API. But it makes the
                # system more safe for no more unexpected parameters pass down
                # to the system. In microversion 2.75, we have blocked all of
                # those additional parameters.
                _strip_additional_query_parameters(request_query_schema, req)
            return func(*args, **kwargs)

        if not hasattr(wrapper, 'request_query_schemas'):
            wrapper.request_query_schemas = Schemas()

        wrapper.request_query_schemas.add_schema(
            request_query_schema, min_version, max_version
        )

        return wrapper

    return add_validator
