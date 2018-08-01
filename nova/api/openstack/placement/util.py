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
from oslo_config import cfg
from oslo_log import log as logging
from oslo_middleware import request_id
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import webob

from nova.api.openstack.placement import errors
from nova.api.openstack.placement import exception
from nova.api.openstack.placement import lib as placement_lib
# NOTE(cdent): avoid cyclical import conflict between util and
# microversion
import nova.api.openstack.placement.microversion
from nova.api.openstack.placement.objects import consumer as consumer_obj
from nova.api.openstack.placement.objects import project as project_obj
from nova.api.openstack.placement.objects import user as user_obj
from nova.i18n import _

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

# Error code handling constants
ENV_ERROR_CODE = 'placement.error_code'
ERROR_CODE_MICROVERSION = (1, 23)

# Querystring-related constants
_QS_RESOURCES = 'resources'
_QS_REQUIRED = 'required'
_QS_MEMBER_OF = 'member_of'
_QS_KEY_PATTERN = re.compile(
        r"^(%s)([1-9][0-9]*)?$" % '|'.join(
        (_QS_RESOURCES, _QS_REQUIRED, _QS_MEMBER_OF)))


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
                best_matches = req.accept.acceptable_offers(types)
                if not best_matches:
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
    # Shortcut to microversion module, to avoid wraps below.
    microversion = nova.api.openstack.placement.microversion

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

    # Version may not be set if we have experienced an error before it
    # is set.
    want_version = environ.get(microversion.MICROVERSION_ENVIRON)
    if want_version and want_version.matches(ERROR_CODE_MICROVERSION):
        error_dict['code'] = environ.get(ENV_ERROR_CODE, errors.DEFAULT)

    # If the request id middleware has had a chance to add an id,
    # put it in the error response.
    if request_id.ENV_REQUEST_ID in environ:
        error_dict['request_id'] = environ[request_id.ENV_REQUEST_ID]

    # When there is a no microversion in the environment and a 406,
    # microversion parsing failed so we need to include microversion
    # min and max information in the error response.
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
        # NOTE(Kevin_Zheng): The webob package throws UnicodeError when
        # param cannot be decoded. Catch this and raise HTTP 400.
        jsonschema.validate(dict(req.GET), schema,
                            format_checker=jsonschema.FormatChecker())
    except (jsonschema.ValidationError, UnicodeDecodeError) as exc:
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


def valid_trait(trait, allow_forbidden):
    """Return True if the provided trait is the expected form.

    When allow_forbidden is True, then a leading '!' is acceptable.
    """
    if trait.startswith('!') and not allow_forbidden:
        return False
    return True


def normalize_traits_qs_param(val, allow_forbidden=False):
    """Parse a traits query string parameter value.

    Note that this method doesn't know or care about the query parameter key,
    which may currently be of the form `required`, `required123`, etc., but
    which may someday also include `preferred`, etc.

    This method currently does no format validation of trait strings, other
    than to ensure they're not zero-length.

    :param val: A traits query parameter value: a comma-separated string of
                trait names.
    :param allow_forbidden: If True, accept forbidden traits (that is, traits
                            prefixed by '!') as a valid form when notifying
                            the caller that the provided value is not properly
                            formed.
    :return: A set of trait names.
    :raises `webob.exc.HTTPBadRequest` if the val parameter is not in the
            expected format.
    """
    ret = set(substr.strip() for substr in val.split(','))
    expected_form = 'HW_CPU_X86_VMX,CUSTOM_MAGIC'
    if allow_forbidden:
        expected_form = 'HW_CPU_X86_VMX,!CUSTOM_MAGIC'
    if not all(trait and valid_trait(trait, allow_forbidden) for trait in ret):
        msg = _("Invalid query string parameters: Expected 'required' "
                "parameter value of the form: %(form)s. "
                "Got: %(val)s") % {'form': expected_form, 'val': val}
        raise webob.exc.HTTPBadRequest(msg)
    return ret


def normalize_member_of_qs_params(req, suffix=''):
    """Given a webob.Request object, validate that the member_of querystring
    parameters are correct. We begin supporting multiple member_of params in
    microversion 1.24.

    :param req: webob.Request object
    :return: A list containing sets of UUIDs of aggregates to filter on
    :raises `webob.exc.HTTPBadRequest` if the microversion requested is <1.24
            and the request contains multiple member_of querystring params
    :raises `webob.exc.HTTPBadRequest` if the val parameter is not in the
            expected format.
    """
    microversion = nova.api.openstack.placement.microversion
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    multi_member_of = want_version.matches((1, 24))
    if not multi_member_of and len(req.GET.getall('member_of' + suffix)) > 1:
        raise webob.exc.HTTPBadRequest(
            _('Multiple member_of%s parameters are not supported') % suffix)
    values = []
    for value in req.GET.getall('member_of' + suffix):
        values.append(normalize_member_of_qs_param(value))
    return values


def normalize_member_of_qs_param(value):
    """Parse a member_of query string parameter value.

    Valid values are either a single UUID, or the prefix 'in:' followed by two
    or more comma-separated UUIDs.

    :param value: A member_of query parameter of either a single UUID, or a
                  comma-separated string of two or more UUIDs, prefixed with
                  the "in:" operator
    :return: A set of UUIDs
    :raises `webob.exc.HTTPBadRequest` if the value parameter is not in the
            expected format.
    """
    if "," in value and not value.startswith("in:"):
        msg = _("Multiple values for 'member_of' must be prefixed with the "
                "'in:' keyword. Got: %s") % value
        raise webob.exc.HTTPBadRequest(msg)
    if value.startswith('in:'):
        value = set(value[3:].split(','))
    else:
        value = set([value])
    # Make sure the values are actually UUIDs.
    for aggr_uuid in value:
        if not uuidutils.is_uuid_like(aggr_uuid):
            msg = _("Invalid query string parameters: Expected 'member_of' "
                    "parameter to contain valid UUID(s). Got: %s") % aggr_uuid
            raise webob.exc.HTTPBadRequest(msg)
    return value


def parse_qs_request_groups(req):
    """Parse numbered resources, traits, and member_of groupings out of a
    querystring dict.

    The input qsdict represents a query string of the form:

    ?resources=$RESOURCE_CLASS_NAME:$AMOUNT,$RESOURCE_CLASS_NAME:$AMOUNT
    &required=$TRAIT_NAME,$TRAIT_NAME&member_of=in:$AGG1_UUID,$AGG2_UUID
    &resources1=$RESOURCE_CLASS_NAME:$AMOUNT,RESOURCE_CLASS_NAME:$AMOUNT
    &required1=$TRAIT_NAME,$TRAIT_NAME&member_of1=$AGG_UUID
    &resources2=$RESOURCE_CLASS_NAME:$AMOUNT,RESOURCE_CLASS_NAME:$AMOUNT
    &required2=$TRAIT_NAME,$TRAIT_NAME&member_of2=$AGG_UUID

    These are parsed in groups according to the numeric suffix of the key.
    For each group, a RequestGroup instance is created containing that group's
    resources, required traits, and member_of. For the (single) group with no
    suffix, the RequestGroup.use_same_provider attribute is False; for the
    numbered groups it is True.

    If a trait in the required parameter is prefixed with ``!`` this
    indicates that that trait must not be present on the resource
    providers in the group. That is, the trait is forbidden. Forbidden traits
    are only processed  if ``allow_forbidden`` is True. This allows the
    caller to control processing based on microversion handling.

    The return is a dict, keyed by the numeric suffix of these RequestGroup
    instances (or the empty string for the unnumbered group).

    As an example, if qsdict represents the query string:

    ?resources=VCPU:2,MEMORY_MB:1024,DISK_GB=50
    &required=HW_CPU_X86_VMX,CUSTOM_STORAGE_RAID
    &member_of=in:9323b2b1-82c9-4e91-bdff-e95e808ef954,8592a199-7d73-4465-8df6-ab00a6243c82   # noqa
    &resources1=SRIOV_NET_VF:2
    &required1=CUSTOM_PHYSNET_PUBLIC,CUSTOM_SWITCH_A
    &resources2=SRIOV_NET_VF:1
    &required2=!CUSTOM_PHYSNET_PUBLIC

    ...the return value will be:

    { '': RequestGroup(
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
              member_of=[
                [9323b2b1-82c9-4e91-bdff-e95e808ef954],
                [8592a199-7d73-4465-8df6-ab00a6243c82,
                 ddbd9226-d6a6-475e-a85f-0609914dd058],
              ],
          ),
      '1': RequestGroup(
              use_same_provider=True,
              resources={
                  "SRIOV_NET_VF": 2,
              },
              required_traits=[
                  "CUSTOM_PHYSNET_PUBLIC",
                  "CUSTOM_SWITCH_A",
              ],
           ),
      '2': RequestGroup(
              use_same_provider=True,
              resources={
                  "SRIOV_NET_VF": 1,
              },
              forbidden_traits=[
                  "CUSTOM_PHYSNET_PUBLIC",
              ],
           ),
    }

    :param req: webob.Request object
    :return: A list of RequestGroup instances.
    :raises `webob.exc.HTTPBadRequest` if any value is malformed, or if a
            trait list is given without corresponding resources.
    """
    microversion = nova.api.openstack.placement.microversion
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    # Control whether we handle forbidden traits.
    allow_forbidden = want_version.matches((1, 22))
    # Temporary dict of the form: { suffix: RequestGroup }
    by_suffix = {}

    def get_request_group(suffix):
        if suffix not in by_suffix:
            rq_grp = placement_lib.RequestGroup(use_same_provider=bool(suffix))
            by_suffix[suffix] = rq_grp
        return by_suffix[suffix]

    for key, val in req.GET.items():
        match = _QS_KEY_PATTERN.match(key)
        if not match:
            continue
        # `prefix` is 'resources', 'required', or 'member_of'
        # `suffix` is an integer string, or None
        prefix, suffix = match.groups()
        suffix = suffix or ''
        request_group = get_request_group(suffix)
        if prefix == _QS_RESOURCES:
            request_group.resources = normalize_resources_qs_param(val)
        elif prefix == _QS_REQUIRED:
            request_group.required_traits = normalize_traits_qs_param(
                val, allow_forbidden=allow_forbidden)
        elif prefix == _QS_MEMBER_OF:
            # special handling of member_of qparam since we allow multiple
            # member_of params at microversion 1.24.
            # NOTE(jaypipes): Yes, this is inefficient to do this when there
            # are multiple member_of query parameters, but we do this so we can
            # error out if someone passes an "orphaned" member_of request
            # group.
            # TODO(jaypipes): Do validation of query parameters using
            # JSONSchema
            request_group.member_of = normalize_member_of_qs_params(
                req, suffix)

    # Ensure any group with 'required' or 'member_of' also has 'resources'.
    orphans = [('required%s' % suff) for suff, group in by_suffix.items()
               if group.required_traits and not group.resources]
    if orphans:
        msg = _('All traits parameters must be associated with resources.  '
                'Found the following orphaned traits keys: %s')
        raise webob.exc.HTTPBadRequest(msg % ', '.join(orphans))
    orphans = [('member_of%s' % suff) for suff, group in by_suffix.items()
               if group.member_of and not group.resources]
    if orphans:
        msg = _('All member_of parameters must be associated with '
                'resources. Found the following orphaned member_of '
                'keys: %s')
        raise webob.exc.HTTPBadRequest(msg % ', '.join(orphans))
    # All request groups must have resources (which is almost, but not quite,
    # verified by the orphan checks above).
    if not all(grp.resources for grp in by_suffix.values()):
        msg = _("All request groups must specify resources.")
        raise webob.exc.HTTPBadRequest(msg)
    # The above would still pass if there were no request groups
    if not by_suffix:
        msg = _("At least one request group (`resources` or `resources{N}`) "
                "is required.")
        raise webob.exc.HTTPBadRequest(msg)

    # Make adjustments for forbidden traits by stripping forbidden out
    # of required.
    if allow_forbidden:
        conflicting_traits = []
        for suff, group in by_suffix.items():
            forbidden = [trait for trait in group.required_traits
                         if trait.startswith('!')]
            group.required_traits = (group.required_traits - set(forbidden))
            group.forbidden_traits = set([trait.lstrip('!') for trait in
                                          forbidden])
            conflicts = group.forbidden_traits & group.required_traits
            if conflicts:
                conflicting_traits.append('required%s: (%s)'
                                          % (suff, ', '.join(conflicts)))
        if conflicting_traits:
            msg = _('Conflicting required and forbidden traits found in the '
                    'following traits keys: %s')
            raise webob.exc.HTTPBadRequest(msg % ', '.join(conflicting_traits))

    return by_suffix


def ensure_consumer(ctx, consumer_uuid, project_id, user_id,
                    consumer_generation, want_version):
    """Ensures there are records in the consumers, projects and users table for
    the supplied external identifiers.

    Returns a tuple containing the populated Consumer object containing Project
    and User sub-objects and a boolean indicating whether a new Consumer object
    was created (as opposed to an existing consumer record retrieved)

    :note: If the supplied project or user external identifiers do not match an
           existing consumer's project and user identifiers, the existing
           consumer's project and user IDs are updated to reflect the supplied
           ones.

    :param ctx: The request context.
    :param consumer_uuid: The uuid of the consumer of the resources.
    :param project_id: The external ID of the project consuming the resources.
    :param user_id: The external ID of the user consuming the resources.
    :param consumer_generation: The generation provided by the user for this
        consumer.
    :param want_version: the microversion matcher.
    :raises webob.exc.HTTPConflict if consumer generation is required and there
            was a mismatch
    """
    created_new_consumer = False
    requires_consumer_generation = want_version.matches((1, 28))
    if project_id is None:
        project_id = CONF.placement.incomplete_consumer_project_id
        user_id = CONF.placement.incomplete_consumer_user_id
    try:
        proj = project_obj.Project.get_by_external_id(ctx, project_id)
    except exception.NotFound:
        # Auto-create the project if we found no record of it...
        try:
            proj = project_obj.Project(ctx, external_id=project_id)
            proj.create()
        except exception.ProjectExists:
            # No worries, another thread created this project already
            proj = project_obj.Project.get_by_external_id(ctx, project_id)
    try:
        user = user_obj.User.get_by_external_id(ctx, user_id)
    except exception.NotFound:
        # Auto-create the user if we found no record of it...
        try:
            user = user_obj.User(ctx, external_id=user_id)
            user.create()
        except exception.UserExists:
            # No worries, another thread created this user already
            user = user_obj.User.get_by_external_id(ctx, user_id)

    try:
        consumer = consumer_obj.Consumer.get_by_uuid(ctx, consumer_uuid)
        if requires_consumer_generation:
            if consumer.generation != consumer_generation:
                raise webob.exc.HTTPConflict(
                    _('consumer generation conflict - '
                      'expected %(expected_gen)s but got %(got_gen)s') %
                      {
                          'expected_gen': consumer.generation,
                          'got_gen': consumer_generation,
                      },
                      comment=errors.CONCURRENT_UPDATE)
        # NOTE(jaypipes): The user may have specified a different project and
        # user external ID than the one that we had for the consumer. If this
        # is the case, go ahead and modify the consumer record with the
        # newly-supplied project/user information, but do not bump the consumer
        # generation (since it will be bumped in the
        # AllocationList.replace_all() method).
        #
        # TODO(jaypipes): This means that there may be a partial update.
        # Imagine a scenario where a user calls POST /allocations, and the
        # payload references two consumers. The first consumer is a new
        # consumer and is auto-created. The second consumer is an existing
        # consumer, but contains a different project or user ID than the
        # existing consumer's record. If the eventual call to
        # AllocationList.replace_all() fails for whatever reason (say, a
        # resource provider generation conflict or out of resources failure),
        # we will end up deleting the auto-created consumer but we MAY not undo
        # the changes to the second consumer's project and user ID. I say MAY
        # and not WILL NOT because I'm not sure that the exception that gets
        # raised from AllocationList.replace_all() will cause the context
        # manager's transaction to rollback automatically. I believe that the
        # same transaction context is used for both util.ensure_consumer() and
        # AllocationList.replace_all() within the same HTTP request, but need
        # to test this to be 100% certain...
        if (project_id != consumer.project.external_id or
                user_id != consumer.user.external_id):
            LOG.debug("Supplied project or user ID for consumer %s was "
                      "different than existing record. Updating consumer "
                      "record.", consumer_uuid)
            consumer.project = proj
            consumer.user = user
            consumer.update()
    except exception.NotFound:
        # If we are attempting to modify or create allocations after 1.26, we
        # need a consumer generation specified. The user must have specified
        # None for the consumer generation if we get here, since there was no
        # existing consumer with this UUID and therefore the user should be
        # indicating that they expect the consumer did not exist.
        if requires_consumer_generation:
            if consumer_generation is not None:
                raise webob.exc.HTTPConflict(
                    _('consumer generation conflict - '
                      'expected null but got %s') % consumer_generation,
                    comment=errors.CONCURRENT_UPDATE)
        # No such consumer. This is common for new allocations. Create the
        # consumer record
        try:
            consumer = consumer_obj.Consumer(
                ctx, uuid=consumer_uuid, project=proj, user=user)
            consumer.create()
            created_new_consumer = True
        except exception.ConsumerExists:
            # No worries, another thread created this user already
            consumer = consumer_obj.Consumer.get_by_uuid(ctx, consumer_uuid)
    return consumer, created_new_consumer
