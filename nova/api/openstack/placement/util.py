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
"""Utility methods for placement API."""

import functools
import re

import jsonschema
from oslo_middleware import request_id
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import webob

from nova.api.openstack.placement import lib as placement_lib
# NOTE(cdent): avoid cyclical import conflict between util and
# microversion
import nova.api.openstack.placement.microversion
from nova.i18n import _


# Querystring-related constants
_QS_RESOURCES = 'resources'
_QS_REQUIRED = 'required'
_QS_KEY_PATTERN = re.compile(
    r"^(%s)([1-9][0-9]*)?$" % '|'.join((_QS_RESOURCES, _QS_REQUIRED)))


# NOTE(cdent): This registers a FormatChecker on the jsonschema
# module. Do not delete this code! Although it appears that nothing
# is using the decorated method it is being used in JSON schema
# validations to check uuid formatted strings.
@jsonschema.FormatChecker.cls_checks('uuid')
def _validate_uuid_format(instance):
    return uuidutils.is_uuid_like(instance)


def check_accept(*types):
    """If accept is set explicitly, try to follow it.

    If there is no match for the incoming accept header
    send a 406 response code.

    If accept is not set send our usual content-type in
    response.
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(req):
            if req.accept:
                best_match = req.accept.best_match(types)
                if not best_match:
                    type_string = ', '.join(types)
                    raise webob.exc.HTTPNotAcceptable(
                        _('Only %(type)s is provided') % {'type': type_string},
                        json_formatter=json_error_formatter)
            return f(req)
        return decorated_function
    return decorator


def extract_json(body, schema):
    """Extract JSON from a body and validate with the provided schema."""
    try:
        data = jsonutils.loads(body)
    except ValueError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Malformed JSON: %(error)s') % {'error': exc},
            json_formatter=json_error_formatter)
    try:
        jsonschema.validate(data, schema,
                            format_checker=jsonschema.FormatChecker())
    except jsonschema.ValidationError as exc:
        raise webob.exc.HTTPBadRequest(
            _('JSON does not validate: %(error)s') % {'error': exc},
            json_formatter=json_error_formatter)
    return data


def inventory_url(environ, resource_provider, resource_class=None):
    url = '%s/inventories' % resource_provider_url(environ, resource_provider)
    if resource_class:
        url = '%s/%s' % (url, resource_class)
    return url


def json_error_formatter(body, status, title, environ):
    """A json_formatter for webob exceptions.

    Follows API-WG guidelines at
    http://specs.openstack.org/openstack/api-wg/guidelines/errors.html
    """
    # Clear out the html that webob sneaks in.
    body = webob.exc.strip_tags(body)
    # Get status code out of status message. webob's error formatter
    # only passes entire status string.
    status_code = int(status.split(None, 1)[0])
    error_dict = {
        'status': status_code,
        'title': title,
        'detail': body
    }
    # If the request id middleware has had a chance to add an id,
    # put it in the error response.
    if request_id.ENV_REQUEST_ID in environ:
        error_dict['request_id'] = environ[request_id.ENV_REQUEST_ID]

    # When there is a no microversion in the environment and a 406,
    # microversion parsing failed so we need to include microversion
    # min and max information in the error response.
    microversion = nova.api.openstack.placement.microversion
    if status_code == 406 and microversion.MICROVERSION_ENVIRON not in environ:
        error_dict['max_version'] = microversion.max_version_string()
        error_dict['min_version'] = microversion.min_version_string()

    return {'errors': [error_dict]}


def pick_last_modified(last_modified, obj):
    """Choose max of last_modified and obj.updated_at or obj.created_at.

    If updated_at is not implemented in `obj` use the current time in UTC.
    """
    try:
        current_modified = (obj.updated_at or obj.created_at)
    except NotImplementedError:
        # If updated_at is not implemented, we are looking at objects that
        # have not come from the database, so "now" is the right modified
        # time.
        current_modified = timeutils.utcnow(with_timezone=True)
    if last_modified:
        last_modified = max(last_modified, current_modified)
    else:
        last_modified = current_modified
    return last_modified


def require_content(content_type):
    """Decorator to require a content type in a handler."""
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(req):
            if req.content_type != content_type:
                # webob's unset content_type is the empty string so
                # set it the error message content to 'None' to make
                # a useful message in that case. This also avoids a
                # KeyError raised when webob.exc eagerly fills in a
                # Template for output we will never use.
                if not req.content_type:
                    req.content_type = 'None'
                raise webob.exc.HTTPUnsupportedMediaType(
                    _('The media type %(bad_type)s is not supported, '
                      'use %(good_type)s') %
                    {'bad_type': req.content_type,
                     'good_type': content_type},
                    json_formatter=json_error_formatter)
            else:
                return f(req)
        return decorated_function
    return decorator


def resource_class_url(environ, resource_class):
    """Produce the URL for a resource class.

    If SCRIPT_NAME is present, it is the mount point of the placement
    WSGI app.
    """
    prefix = environ.get('SCRIPT_NAME', '')
    return '%s/resource_classes/%s' % (prefix, resource_class.name)


def resource_provider_url(environ, resource_provider):
    """Produce the URL for a resource provider.

    If SCRIPT_NAME is present, it is the mount point of the placement
    WSGI app.
    """
    prefix = environ.get('SCRIPT_NAME', '')
    return '%s/resource_providers/%s' % (prefix, resource_provider.uuid)


def trait_url(environ, trait):
    """Produce the URL for a trait.

    If SCRIPT_NAME is present, it is the mount point of the placement
    WSGI app.
    """
    prefix = environ.get('SCRIPT_NAME', '')
    return '%s/traits/%s' % (prefix, trait.name)


def validate_query_params(req, schema):
    try:
        jsonschema.validate(dict(req.GET), schema,
                            format_checker=jsonschema.FormatChecker())
    except jsonschema.ValidationError as exc:
        raise webob.exc.HTTPBadRequest(
            _('Invalid query string parameters: %(exc)s') %
            {'exc': exc})


def wsgi_path_item(environ, name):
    """Extract the value of a named field in a URL.

    Return None if the name is not present or there are no path items.
    """
    # NOTE(cdent): For the time being we don't need to urldecode
    # the value as the entire placement API has paths that accept no
    # encoded values.
    try:
        return environ['wsgiorg.routing_args'][1][name]
    except (KeyError, IndexError):
        return None


def normalize_resources_qs_param(qs):
    """Given a query string parameter for resources, validate it meets the
    expected format and return a dict of amounts, keyed by resource class name.

    The expected format of the resources parameter looks like so:

        $RESOURCE_CLASS_NAME:$AMOUNT,$RESOURCE_CLASS_NAME:$AMOUNT

    So, if the user was looking for resource providers that had room for an
    instance that will consume 2 vCPUs, 1024 MB of RAM and 50GB of disk space,
    they would use the following query string:

        ?resources=VCPU:2,MEMORY_MB:1024,DISK_GB:50

    The returned value would be:

        {
            "VCPU": 2,
            "MEMORY_MB": 1024,
            "DISK_GB": 50,
        }

    :param qs: The value of the 'resources' query string parameter
    :raises `webob.exc.HTTPBadRequest` if the parameter's value isn't in the
            expected format.
    """
    if qs.strip() == "":
        msg = _('Badly formed resources parameter. Expected resources '
                'query string parameter in form: '
                '?resources=VCPU:2,MEMORY_MB:1024. Got: empty string.')
        raise webob.exc.HTTPBadRequest(msg)

    result = {}
    resource_tuples = qs.split(',')
    for rt in resource_tuples:
        try:
            rc_name, amount = rt.split(':')
        except ValueError:
            msg = _('Badly formed resources parameter. Expected resources '
                    'query string parameter in form: '
                    '?resources=VCPU:2,MEMORY_MB:1024. Got: %s.')
            msg = msg % rt
            raise webob.exc.HTTPBadRequest(msg)
        try:
            amount = int(amount)
        except ValueError:
            msg = _('Requested resource %(resource_name)s expected positive '
                    'integer amount. Got: %(amount)s.')
            msg = msg % {
                'resource_name': rc_name,
                'amount': amount,
            }
            raise webob.exc.HTTPBadRequest(msg)
        if amount < 1:
            msg = _('Requested resource %(resource_name)s requires '
                    'amount >= 1. Got: %(amount)d.')
            msg = msg % {
                'resource_name': rc_name,
                'amount': amount,
            }
            raise webob.exc.HTTPBadRequest(msg)
        result[rc_name] = amount
    return result


def normalize_traits_qs_param(val):
    """Parse a traits query string parameter value.

    Note that this method doesn't know or care about the query parameter key,
    which may currently be of the form `required`, `required123`, etc., but
    which may someday also include `preferred`, etc.

    This method currently does no format validation of trait strings, other
    than to ensure they're not zero-length.

    :param val: A traits query parameter value: a comma-separated string of
                trait names.
    :return: A set of trait names.
    :raises `webob.exc.HTTPBadRequest` if the val parameter is not in the
            expected format.
    """
    ret = set(substr.strip() for substr in val.split(','))
    if not all(trait for trait in ret):
        msg = _("Invalid query string parameters: Expected 'required' "
                "parameter value of the form: HW_CPU_X86_VMX,CUSTOM_MAGIC. "
                "Got: %s") % val
        raise webob.exc.HTTPBadRequest(msg)
    return ret


def parse_qs_request_groups(qsdict):
    """Parse numbered resources and traits groupings out of a querystring dict.

    The input qsdict represents a query string of the form:

    ?resources=$RESOURCE_CLASS_NAME:$AMOUNT,$RESOURCE_CLASS_NAME:$AMOUNT
    &required=$TRAIT_NAME,$TRAIT_NAME
    &resources1=$RESOURCE_CLASS_NAME:$AMOUNT,RESOURCE_CLASS_NAME:$AMOUNT
    &required1=$TRAIT_NAME,$TRAIT_NAME
    &resources2=$RESOURCE_CLASS_NAME:$AMOUNT,RESOURCE_CLASS_NAME:$AMOUNT
    &required2=$TRAIT_NAME,$TRAIT_NAME

    These are parsed in groups according to the numeric suffix of the key.
    For each group, a RequestGroup instance is created containing that group's
    resources and required traits.  For the (single) group with no suffix, the
    RequestGroup.use_same_provider attribute is False; for the numbered groups
    it is True.

    The return is a list of these RequestGroup instances.

    As an example, if qsdict represents the query string:

    ?resources=VCPU:2,MEMORY_MB:1024,DISK_GB=50
    &required=HW_CPU_X86_VMX,CUSTOM_STORAGE_RAID
    &resources1=SRIOV_NET_VF:2
    &required1=CUSTOM_PHYSNET_PUBLIC,CUSTOM_SWITCH_A
    &resources2=SRIOV_NET_VF:1
    &required2=CUSTOM_PHYSNET_PRIVATE

    ...the return value will be:

    [ RequestGroup(
          use_same_provider=False,
          resources={
              "VCPU": 2,
              "MEMORY_MB": 1024,
              "DISK_GB" 50,
          },
          required_traits=[
              "HW_CPU_X86_VMX",
              "CUSTOM_STORAGE_RAID",
          ],
      ),
      RequestGroup(
          use_same_provider=True,
          resources={
              "SRIOV_NET_VF": 2,
          },
          required_traits=[
              "CUSTOM_PHYSNET_PUBLIC",
              "CUSTOM_SWITCH_A",
          ],
      ),
      RequestGroup(
          use_same_provider=True,
          resources={
              "SRIOV_NET_VF": 1,
          },
          required_traits=[
              "CUSTOM_PHYSNET_PRIVATE",
          ],
      ),
    ]

    :param qsdict: The MultiDict representing the querystring on a GET.
    :return: A list of RequestGroup instances.
    :raises `webob.exc.HTTPBadRequest` if any value is malformed, or if a
            trait list is given without corresponding resources.
    """
    # Temporary dict of the form: { suffix: RequestGroup }
    by_suffix = {}

    def get_request_group(suffix):
        if suffix not in by_suffix:
            rq_grp = placement_lib.RequestGroup(use_same_provider=bool(suffix))
            by_suffix[suffix] = rq_grp
        return by_suffix[suffix]

    for key, val in qsdict.items():
        match = _QS_KEY_PATTERN.match(key)
        if not match:
            continue
        # `prefix` is 'resources' or 'required'
        # `suffix` is an integer string, or None
        prefix, suffix = match.groups()
        request_group = get_request_group(suffix or '')
        if prefix == _QS_RESOURCES:
            request_group.resources = normalize_resources_qs_param(val)
        elif prefix == _QS_REQUIRED:
            request_group.required_traits = normalize_traits_qs_param(val)

    # Ensure any group with 'required' also has 'resources'.
    orphans = [('required%s' % suff) for suff, group in by_suffix.items()
               if group.required_traits and not group.resources]
    if orphans:
        msg = _('All traits parameters must be associated with resources.  '
                'Found the following orphaned traits keys: %s')
        raise webob.exc.HTTPBadRequest(msg % ', '.join(orphans))

    # NOTE(efried): The sorting is not necessary for the API, but it makes
    # testing easier.
    return [by_suffix[suff] for suff in sorted(by_suffix)]
