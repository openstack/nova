# Copyright 2010 OpenStack Foundation
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

import collections
import functools
import itertools
import re

from oslo_log import log as logging
from oslo_utils import strutils
import six
import six.moves.urllib.parse as urlparse
import webob
from webob import exc

from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova import quota
from nova import utils

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS


_STATE_MAP = {
    vm_states.ACTIVE: {
        'default': 'ACTIVE',
        task_states.REBOOTING: 'REBOOT',
        task_states.REBOOT_PENDING: 'REBOOT',
        task_states.REBOOT_STARTED: 'REBOOT',
        task_states.REBOOTING_HARD: 'HARD_REBOOT',
        task_states.REBOOT_PENDING_HARD: 'HARD_REBOOT',
        task_states.REBOOT_STARTED_HARD: 'HARD_REBOOT',
        task_states.UPDATING_PASSWORD: 'PASSWORD',
        task_states.REBUILDING: 'REBUILD',
        task_states.REBUILD_BLOCK_DEVICE_MAPPING: 'REBUILD',
        task_states.REBUILD_SPAWNING: 'REBUILD',
        task_states.MIGRATING: 'MIGRATING',
        task_states.RESIZE_PREP: 'RESIZE',
        task_states.RESIZE_MIGRATING: 'RESIZE',
        task_states.RESIZE_MIGRATED: 'RESIZE',
        task_states.RESIZE_FINISH: 'RESIZE',
    },
    vm_states.BUILDING: {
        'default': 'BUILD',
    },
    vm_states.STOPPED: {
        'default': 'SHUTOFF',
        task_states.RESIZE_PREP: 'RESIZE',
        task_states.RESIZE_MIGRATING: 'RESIZE',
        task_states.RESIZE_MIGRATED: 'RESIZE',
        task_states.RESIZE_FINISH: 'RESIZE',
        task_states.REBUILDING: 'REBUILD',
        task_states.REBUILD_BLOCK_DEVICE_MAPPING: 'REBUILD',
        task_states.REBUILD_SPAWNING: 'REBUILD',
    },
    vm_states.RESIZED: {
        'default': 'VERIFY_RESIZE',
        # Note(maoy): the OS API spec 1.1 doesn't have CONFIRMING_RESIZE
        # state so we comment that out for future reference only.
        # task_states.RESIZE_CONFIRMING: 'CONFIRMING_RESIZE',
        task_states.RESIZE_REVERTING: 'REVERT_RESIZE',
    },
    vm_states.PAUSED: {
        'default': 'PAUSED',
        task_states.MIGRATING: 'MIGRATING',
    },
    vm_states.SUSPENDED: {
        'default': 'SUSPENDED',
    },
    vm_states.RESCUED: {
        'default': 'RESCUE',
    },
    vm_states.ERROR: {
        'default': 'ERROR',
        task_states.REBUILDING: 'REBUILD',
        task_states.REBUILD_BLOCK_DEVICE_MAPPING: 'REBUILD',
        task_states.REBUILD_SPAWNING: 'REBUILD',
    },
    vm_states.DELETED: {
        'default': 'DELETED',
    },
    vm_states.SOFT_DELETED: {
        'default': 'SOFT_DELETED',
    },
    vm_states.SHELVED: {
        'default': 'SHELVED',
    },
    vm_states.SHELVED_OFFLOADED: {
        'default': 'SHELVED_OFFLOADED',
    },
}


def status_from_state(vm_state, task_state='default'):
    """Given vm_state and task_state, return a status string."""
    task_map = _STATE_MAP.get(vm_state, dict(default='UNKNOWN'))
    status = task_map.get(task_state, task_map['default'])
    if status == "UNKNOWN":
        LOG.error("status is UNKNOWN from vm_state=%(vm_state)s "
                  "task_state=%(task_state)s. Bad upgrade or db "
                  "corrupted?",
                  {'vm_state': vm_state, 'task_state': task_state})
    return status


def task_and_vm_state_from_status(statuses):
    """Map the server's multiple status strings to list of vm states and
    list of task states.
    """
    vm_states = set()
    task_states = set()
    lower_statuses = [status.lower() for status in statuses]
    for state, task_map in _STATE_MAP.items():
        for task_state, mapped_state in task_map.items():
            status_string = mapped_state
            if status_string.lower() in lower_statuses:
                vm_states.add(state)
                task_states.add(task_state)
    # Add sort to avoid different order on set in Python 3
    return sorted(vm_states), sorted(task_states)


def get_sort_params(input_params, default_key='created_at',
                    default_dir='desc'):
    """Retrieves sort keys/directions parameters.

    Processes the parameters to create a list of sort keys and sort directions
    that correspond to the 'sort_key' and 'sort_dir' parameter values. These
    sorting parameters can be specified multiple times in order to generate
    the list of sort keys and directions.

    The input parameters are not modified.

    :param input_params: webob.multidict of request parameters (from
                         nova.wsgi.Request.params)
    :param default_key: default sort key value, added to the list if no
                        'sort_key' parameters are supplied
    :param default_dir: default sort dir value, added to the list if no
                        'sort_dir' parameters are supplied
    :returns: list of sort keys, list of sort dirs
    """
    params = input_params.copy()
    sort_keys = []
    sort_dirs = []
    while 'sort_key' in params:
        sort_keys.append(params.pop('sort_key').strip())
    while 'sort_dir' in params:
        sort_dirs.append(params.pop('sort_dir').strip())
    if len(sort_keys) == 0 and default_key:
        sort_keys.append(default_key)
    if len(sort_dirs) == 0 and default_dir:
        sort_dirs.append(default_dir)
    return sort_keys, sort_dirs


def get_pagination_params(request):
    """Return marker, limit tuple from request.

    :param request: `wsgi.Request` possibly containing 'marker' and 'limit'
                    GET variables. 'marker' is the id of the last element
                    the client has seen, and 'limit' is the maximum number
                    of items to return. If 'limit' is not specified, 0, or
                    > max_limit, we default to max_limit. Negative values
                    for either marker or limit will cause
                    exc.HTTPBadRequest() exceptions to be raised.

    """
    params = {}
    if 'limit' in request.GET:
        params['limit'] = _get_int_param(request, 'limit')
    if 'page_size' in request.GET:
        params['page_size'] = _get_int_param(request, 'page_size')
    if 'marker' in request.GET:
        params['marker'] = _get_marker_param(request)
    if 'offset' in request.GET:
        params['offset'] = _get_int_param(request, 'offset')
    return params


def _get_int_param(request, param):
    """Extract integer param from request or fail."""
    try:
        int_param = utils.validate_integer(request.GET[param], param,
                                           min_value=0)
    except exception.InvalidInput as e:
        raise webob.exc.HTTPBadRequest(explanation=e.format_message())
    return int_param


def _get_marker_param(request):
    """Extract marker id from request or fail."""
    return request.GET['marker']


def limited(items, request):
    """Return a slice of items according to requested offset and limit.

    :param items: A sliceable entity
    :param request: ``wsgi.Request`` possibly containing 'offset' and 'limit'
                    GET variables. 'offset' is where to start in the list,
                    and 'limit' is the maximum number of items to return. If
                    'limit' is not specified, 0, or > max_limit, we default
                    to max_limit. Negative values for either offset or limit
                    will cause exc.HTTPBadRequest() exceptions to be raised.
    """
    params = get_pagination_params(request)
    offset = params.get('offset', 0)
    limit = CONF.api.max_limit
    limit = min(limit, params.get('limit') or limit)

    return items[offset:(offset + limit)]


def get_limit_and_marker(request):
    """Get limited parameter from request."""
    params = get_pagination_params(request)
    limit = CONF.api.max_limit
    limit = min(limit, params.get('limit', limit))
    marker = params.get('marker', None)

    return limit, marker


def get_id_from_href(href):
    """Return the id or uuid portion of a url.

    Given: 'http://www.foo.com/bar/123?q=4'
    Returns: '123'

    Given: 'http://www.foo.com/bar/abc123?q=4'
    Returns: 'abc123'

    """
    return urlparse.urlsplit("%s" % href).path.split('/')[-1]


def remove_trailing_version_from_href(href):
    """Removes the api version from the href.

    Given: 'http://www.nova.com/compute/v1.1'
    Returns: 'http://www.nova.com/compute'

    Given: 'http://www.nova.com/v1.1'
    Returns: 'http://www.nova.com'

    """
    parsed_url = urlparse.urlsplit(href)
    url_parts = parsed_url.path.rsplit('/', 1)

    # NOTE: this should match vX.X or vX
    expression = re.compile(r'^v([0-9]+|[0-9]+\.[0-9]+)(/.*|$)')
    if not expression.match(url_parts.pop()):
        LOG.debug('href %s does not contain version', href)
        raise ValueError(_('href %s does not contain version') % href)

    new_path = url_join(*url_parts)
    parsed_url = list(parsed_url)
    parsed_url[2] = new_path
    return urlparse.urlunsplit(parsed_url)


def check_img_metadata_properties_quota(context, metadata):
    if not metadata:
        return
    try:
        QUOTAS.limit_check(context, metadata_items=len(metadata))
    except exception.OverQuota:
        expl = _("Image metadata limit exceeded")
        raise webob.exc.HTTPForbidden(explanation=expl)


def get_networks_for_instance_from_nw_info(nw_info):
    networks = collections.OrderedDict()
    for vif in nw_info:
        ips = vif.fixed_ips()
        floaters = vif.floating_ips()
        label = vif['network']['label']
        if label not in networks:
            networks[label] = {'ips': [], 'floating_ips': []}
        for ip in itertools.chain(ips, floaters):
            ip['mac_address'] = vif['address']
        networks[label]['ips'].extend(ips)
        networks[label]['floating_ips'].extend(floaters)
    return networks


def get_networks_for_instance(context, instance):
    """Returns a prepared nw_info list for passing into the view builders

    We end up with a data structure like::

        {'public': {'ips': [{'address': '10.0.0.1',
                             'version': 4,
                             'mac_address': 'aa:aa:aa:aa:aa:aa'},
                            {'address': '2001::1',
                             'version': 6,
                             'mac_address': 'aa:aa:aa:aa:aa:aa'}],
                    'floating_ips': [{'address': '172.16.0.1',
                                      'version': 4,
                                      'mac_address': 'aa:aa:aa:aa:aa:aa'},
                                     {'address': '172.16.2.1',
                                      'version': 4,
                                      'mac_address': 'aa:aa:aa:aa:aa:aa'}]},
         ...}
    """
    nw_info = instance.get_network_info()
    return get_networks_for_instance_from_nw_info(nw_info)


def raise_http_conflict_for_instance_invalid_state(exc, action, server_id):
    """Raises a webob.exc.HTTPConflict instance containing a message
    appropriate to return via the API based on the original
    InstanceInvalidState exception.
    """
    attr = exc.kwargs.get('attr')
    state = exc.kwargs.get('state')
    if attr is not None and state is not None:
        msg = _("Cannot '%(action)s' instance %(server_id)s while it is in "
                "%(attr)s %(state)s") % {'action': action, 'attr': attr,
                                         'state': state,
                                         'server_id': server_id}
    else:
        # At least give some meaningful message
        msg = _("Instance %(server_id)s is in an invalid state for "
                "'%(action)s'") % {'action': action, 'server_id': server_id}
    raise webob.exc.HTTPConflict(explanation=msg)


def check_snapshots_enabled(f):
    @functools.wraps(f)
    def inner(*args, **kwargs):
        if not CONF.api.allow_instance_snapshots:
            LOG.warning('Rejecting snapshot request, snapshots currently'
                        ' disabled')
            msg = _("Instance snapshots are not permitted at this time.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return f(*args, **kwargs)
    return inner


def url_join(*parts):
    """Convenience method for joining parts of a URL

    Any leading and trailing '/' characters are removed, and the parts joined
    together with '/' as a separator. If last element of 'parts' is an empty
    string, the returned URL will have a trailing slash.
    """
    parts = parts or [""]
    clean_parts = [part.strip("/") for part in parts if part]
    if not parts[-1]:
        # Empty last element should add a trailing slash
        clean_parts.append("")
    return "/".join(clean_parts)


class ViewBuilder(object):
    """Model API responses as dictionaries."""

    def _get_project_id(self, request):
        """Get project id from request url if present or empty string
        otherwise
        """
        project_id = request.environ["nova.context"].project_id
        if project_id and project_id in request.url:
            return project_id
        return ''

    def _get_links(self, request, identifier, collection_name):
        return [{
            "rel": "self",
            "href": self._get_href_link(request, identifier, collection_name),
        },
        {
            "rel": "bookmark",
            "href": self._get_bookmark_link(request,
                                            identifier,
                                            collection_name),
        }]

    def _get_next_link(self, request, identifier, collection_name):
        """Return href string with proper limit and marker params."""
        params = collections.OrderedDict(sorted(request.params.items()))
        params["marker"] = identifier
        prefix = self._update_compute_link_prefix(request.application_url)
        url = url_join(prefix,
                       self._get_project_id(request),
                       collection_name)
        return "%s?%s" % (url, urlparse.urlencode(params))

    def _get_href_link(self, request, identifier, collection_name):
        """Return an href string pointing to this object."""
        prefix = self._update_compute_link_prefix(request.application_url)
        return url_join(prefix,
                        self._get_project_id(request),
                        collection_name,
                        str(identifier))

    def _get_bookmark_link(self, request, identifier, collection_name):
        """Create a URL that refers to a specific resource."""
        base_url = remove_trailing_version_from_href(request.application_url)
        base_url = self._update_compute_link_prefix(base_url)
        return url_join(base_url,
                        self._get_project_id(request),
                        collection_name,
                        str(identifier))

    def _get_collection_links(self,
                              request,
                              items,
                              collection_name,
                              id_key="uuid"):
        """Retrieve 'next' link, if applicable. This is included if:
        1) 'limit' param is specified and equals the number of items.
        2) 'limit' param is specified but it exceeds CONF.api.max_limit,
        in this case the number of items is CONF.api.max_limit.
        3) 'limit' param is NOT specified but the number of items is
        CONF.api.max_limit.
        """
        links = []
        max_items = min(
            int(request.params.get("limit", CONF.api.max_limit)),
            CONF.api.max_limit)
        if max_items and max_items == len(items):
            last_item = items[-1]
            if id_key in last_item:
                last_item_id = last_item[id_key]
            elif 'id' in last_item:
                last_item_id = last_item["id"]
            else:
                last_item_id = last_item["flavorid"]
            links.append({
                "rel": "next",
                "href": self._get_next_link(request,
                                            last_item_id,
                                            collection_name),
            })
        return links

    def _update_link_prefix(self, orig_url, prefix):
        if not prefix:
            return orig_url
        url_parts = list(urlparse.urlsplit(orig_url))
        prefix_parts = list(urlparse.urlsplit(prefix))
        url_parts[0:2] = prefix_parts[0:2]
        url_parts[2] = prefix_parts[2] + url_parts[2]
        return urlparse.urlunsplit(url_parts).rstrip('/')

    def _update_glance_link_prefix(self, orig_url):
        return self._update_link_prefix(orig_url, CONF.api.glance_link_prefix)

    def _update_compute_link_prefix(self, orig_url):
        return self._update_link_prefix(orig_url, CONF.api.compute_link_prefix)


def get_instance(compute_api, context, instance_id, expected_attrs=None):
    """Fetch an instance from the compute API, handling error checking."""
    try:
        return compute_api.get(context, instance_id,
                               expected_attrs=expected_attrs)
    except exception.InstanceNotFound as e:
        raise exc.HTTPNotFound(explanation=e.format_message())


def normalize_name(name):
    # NOTE(alex_xu): This method is used by v2.1 legacy v2 compat mode.
    # In the legacy v2 API, some of APIs strip the spaces and some of APIs not.
    # The v2.1 disallow leading/trailing, for compatible v2 API and consistent,
    # we enable leading/trailing spaces and strip spaces in legacy v2 compat
    # mode. Althrough in legacy v2 API there are some APIs didn't strip spaces,
    # but actually leading/trailing spaces(that means user depend on leading/
    # trailing spaces distinguish different instance) is pointless usecase.
    return name.strip()


def raise_feature_not_supported(msg=None):
    if msg is None:
        msg = _("The requested functionality is not supported.")
    raise webob.exc.HTTPNotImplemented(explanation=msg)


def get_flavor(context, flavor_id):
    try:
        return objects.Flavor.get_by_flavor_id(context, flavor_id)
    except exception.FlavorNotFound as error:
        raise exc.HTTPNotFound(explanation=error.format_message())


def check_cells_enabled(function):
    @functools.wraps(function)
    def inner(*args, **kwargs):
        if not CONF.cells.enable:
            raise_feature_not_supported()
        return function(*args, **kwargs)
    return inner


def is_all_tenants(search_opts):
    """Checks to see if the all_tenants flag is in search_opts

    :param dict search_opts: The search options for a request
    :returns: boolean indicating if all_tenants are being requested or not
    """
    all_tenants = search_opts.get('all_tenants')
    if all_tenants:
        try:
            all_tenants = strutils.bool_from_string(all_tenants, True)
        except ValueError as err:
            raise exception.InvalidInput(six.text_type(err))
    else:
        # The empty string is considered enabling all_tenants
        all_tenants = 'all_tenants' in search_opts
    return all_tenants
