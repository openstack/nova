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

import functools
import itertools
import os
import re

from oslo.config import cfg
import six.moves.urllib.parse as urlparse
import webob
from webob import exc

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova import quota

osapi_opts = [
    cfg.IntOpt('osapi_max_limit',
               default=1000,
               help='The maximum number of items returned in a single '
                    'response from a collection resource'),
    cfg.StrOpt('osapi_compute_link_prefix',
               help='Base URL that will be presented to users in links '
                    'to the OpenStack Compute API'),
    cfg.StrOpt('osapi_glance_link_prefix',
               help='Base URL that will be presented to users in links '
                    'to glance resources'),
]
CONF = cfg.CONF
CONF.register_opts(osapi_opts)

LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS

CONF.import_opt('enable', 'nova.cells.opts', group='cells')

# NOTE(cyeoh): A common regexp for acceptable names (user supplied)
# that we want all new extensions to conform to unless there is a very
# good reason not to.
VALID_NAME_REGEX = re.compile("^(?! )[\w. _-]+(?<! )$", re.UNICODE)

XML_NS_V11 = 'http://docs.openstack.org/compute/api/v1.1'


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
    },
    vm_states.RESIZED: {
        'default': 'VERIFY_RESIZE',
        # Note(maoy): the OS API spec 1.1 doesn't have CONFIRMING_RESIZE
        # state so we comment that out for future reference only.
        #task_states.RESIZE_CONFIRMING: 'CONFIRMING_RESIZE',
        task_states.RESIZE_REVERTING: 'REVERT_RESIZE',
    },
    vm_states.PAUSED: {
        'default': 'PAUSED',
    },
    vm_states.SUSPENDED: {
        'default': 'SUSPENDED',
    },
    vm_states.RESCUED: {
        'default': 'RESCUE',
    },
    vm_states.ERROR: {
        'default': 'ERROR',
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
        LOG.error(_("status is UNKNOWN from vm_state=%(vm_state)s "
                    "task_state=%(task_state)s. Bad upgrade or db "
                    "corrupted?"),
                  {'vm_state': vm_state, 'task_state': task_state})
    return status


def task_and_vm_state_from_status(status):
    """Map the server status string to list of vm states and
    list of task states.
    """
    vm_states = set()
    task_states = set()
    for state, task_map in _STATE_MAP.iteritems():
        for task_state, mapped_state in task_map.iteritems():
            status_string = mapped_state
            if status.lower() == status_string.lower():
                vm_states.add(state)
                task_states.add(task_state)
    # Add sort to avoid different order on set in Python 3
    return sorted(vm_states), sorted(task_states)


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
    return params


def _get_int_param(request, param):
    """Extract integer param from request or fail."""
    try:
        int_param = int(request.GET[param])
    except ValueError:
        msg = _('%s param must be an integer') % param
        raise webob.exc.HTTPBadRequest(explanation=msg)
    if int_param < 0:
        msg = _('%s param must be positive') % param
        raise webob.exc.HTTPBadRequest(explanation=msg)
    return int_param


def _get_marker_param(request):
    """Extract marker id from request or fail."""
    return request.GET['marker']


def limited(items, request, max_limit=CONF.osapi_max_limit):
    """Return a slice of items according to requested offset and limit.

    :param items: A sliceable entity
    :param request: ``wsgi.Request`` possibly containing 'offset' and 'limit'
                    GET variables. 'offset' is where to start in the list,
                    and 'limit' is the maximum number of items to return. If
                    'limit' is not specified, 0, or > max_limit, we default
                    to max_limit. Negative values for either offset or limit
                    will cause exc.HTTPBadRequest() exceptions to be raised.
    :kwarg max_limit: The maximum number of items to return from 'items'
    """
    try:
        offset = int(request.GET.get('offset', 0))
    except ValueError:
        msg = _('offset param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    try:
        limit = int(request.GET.get('limit', max_limit))
    except ValueError:
        msg = _('limit param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if limit < 0:
        msg = _('limit param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if offset < 0:
        msg = _('offset param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    limit = min(max_limit, limit or max_limit)
    range_end = offset + limit
    return items[offset:range_end]


def get_limit_and_marker(request, max_limit=CONF.osapi_max_limit):
    """get limited parameter from request."""
    params = get_pagination_params(request)
    limit = params.get('limit', max_limit)
    limit = min(max_limit, limit)
    marker = params.get('marker')

    return limit, marker


def limited_by_marker(items, request, max_limit=CONF.osapi_max_limit):
    """Return a slice of items according to the requested marker and limit."""
    limit, marker = get_limit_and_marker(request, max_limit)

    limit = min(max_limit, limit)
    start_index = 0
    if marker:
        start_index = -1
        for i, item in enumerate(items):
            if 'flavorid' in item:
                if item['flavorid'] == marker:
                    start_index = i + 1
                    break
            elif item['id'] == marker or item.get('uuid') == marker:
                start_index = i + 1
                break
        if start_index < 0:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)
    range_end = start_index + limit
    return items[start_index:range_end]


def get_id_from_href(href):
    """Return the id or uuid portion of a url.

    Given: 'http://www.foo.com/bar/123?q=4'
    Returns: '123'

    Given: 'http://www.foo.com/bar/abc123?q=4'
    Returns: 'abc123'

    """
    return urlparse.urlsplit("%s" % href).path.split('/')[-1]


def remove_version_from_href(href):
    """Removes the first api version from the href.

    Given: 'http://www.nova.com/v1.1/123'
    Returns: 'http://www.nova.com/123'

    Given: 'http://www.nova.com/v1.1'
    Returns: 'http://www.nova.com'

    """
    parsed_url = urlparse.urlsplit(href)
    url_parts = parsed_url.path.split('/', 2)

    # NOTE: this should match vX.X or vX
    expression = re.compile(r'^v([0-9]+|[0-9]+\.[0-9]+)(/.*|$)')
    if expression.match(url_parts[1]):
        del url_parts[1]

    new_path = '/'.join(url_parts)

    if new_path == parsed_url.path:
        msg = _('href %s does not contain version') % href
        LOG.debug(msg)
        raise ValueError(msg)

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
        raise webob.exc.HTTPRequestEntityTooLarge(explanation=expl,
                                                headers={'Retry-After': 0})

    #  check the key length.
    if isinstance(metadata, dict):
        for key, value in metadata.iteritems():
            if len(key) == 0:
                expl = _("Image metadata key cannot be blank")
                raise webob.exc.HTTPBadRequest(explanation=expl)
            if len(key) > 255:
                expl = _("Image metadata key too long")
                raise webob.exc.HTTPBadRequest(explanation=expl)
    else:
        expl = _("Invalid image metadata")
        raise webob.exc.HTTPBadRequest(explanation=expl)


def dict_to_query_str(params):
    # TODO(throughnothing): we should just use urllib.urlencode instead of this
    # But currently we don't work with urlencoded url's
    param_str = ""
    for key, val in params.iteritems():
        param_str = param_str + '='.join([str(key), str(val)]) + '&'

    return param_str.rstrip('&')


def get_networks_for_instance_from_nw_info(nw_info):
    networks = {}
    for vif in nw_info:
        ips = vif.fixed_ips()
        floaters = vif.floating_ips()
        label = vif['network']['label']
        if label not in networks:
            networks[label] = {'ips': [], 'floating_ips': []}

        networks[label]['ips'].extend(ips)
        networks[label]['floating_ips'].extend(floaters)
        for ip in itertools.chain(networks[label]['ips'],
                                  networks[label]['floating_ips']):
            ip['mac_address'] = vif['address']
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
    nw_info = compute_utils.get_nw_info_for_instance(instance)
    return get_networks_for_instance_from_nw_info(nw_info)


def raise_http_conflict_for_instance_invalid_state(exc, action):
    """Raises a webob.exc.HTTPConflict instance containing a message
    appropriate to return via the API based on the original
    InstanceInvalidState exception.
    """
    attr = exc.kwargs.get('attr')
    state = exc.kwargs.get('state')
    not_launched = exc.kwargs.get('not_launched')
    if attr and state:
        msg = _("Cannot '%(action)s' while instance is in %(attr)s "
                "%(state)s") % {'action': action, 'attr': attr, 'state': state}
    elif not_launched:
        msg = _("Cannot '%s' an instance which has never been active") % action
    else:
        # At least give some meaningful message
        msg = _("Instance is in an invalid state for '%s'") % action
    raise webob.exc.HTTPConflict(explanation=msg)


class MetadataDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = xmlutil.safe_minidom_parse_string(text)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}


class MetaItemDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = xmlutil.safe_minidom_parse_string(text)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


class MetadataXMLDeserializer(wsgi.XMLDeserializer):

    def extract_metadata(self, metadata_node):
        """Marshal the metadata attribute of a parsed request."""
        if metadata_node is None:
            return {}
        metadata = {}
        for meta_node in self.find_children_named(metadata_node, "meta"):
            key = meta_node.getAttribute("key")
            metadata[key] = self.extract_text(meta_node)
        return metadata

    def _extract_metadata_container(self, datastring):
        dom = xmlutil.safe_minidom_parse_string(datastring)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}

    def create(self, datastring):
        return self._extract_metadata_container(datastring)

    def update_all(self, datastring):
        return self._extract_metadata_container(datastring)

    def update(self, datastring):
        dom = xmlutil.safe_minidom_parse_string(datastring)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


metadata_nsmap = {None: xmlutil.XMLNS_V11}


class MetaItemTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        sel = xmlutil.Selector('meta', xmlutil.get_items, 0)
        root = xmlutil.TemplateElement('meta', selector=sel)
        root.set('key', 0)
        root.text = 1
        return xmlutil.MasterTemplate(root, 1, nsmap=metadata_nsmap)


class MetadataTemplateElement(xmlutil.TemplateElement):
    def will_render(self, datum):
        return True


class MetadataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = MetadataTemplateElement('metadata', selector='metadata')
        elem = xmlutil.SubTemplateElement(root, 'meta',
                                          selector=xmlutil.get_items)
        elem.set('key', 0)
        elem.text = 1
        return xmlutil.MasterTemplate(root, 1, nsmap=metadata_nsmap)


def check_snapshots_enabled(f):
    @functools.wraps(f)
    def inner(*args, **kwargs):
        if not CONF.allow_instance_snapshots:
            LOG.warn(_('Rejecting snapshot request, snapshots currently'
                       ' disabled'))
            msg = _("Instance snapshots are not permitted at this time.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return f(*args, **kwargs)
    return inner


class ViewBuilder(object):
    """Model API responses as dictionaries."""

    def _get_project_id(self, request):
        """Get project id from request url if present or empty string
        otherwise
        """
        project_id = request.environ["nova.context"].project_id
        if project_id in request.url:
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
        params = request.params.copy()
        params["marker"] = identifier
        prefix = self._update_compute_link_prefix(request.application_url)
        url = os.path.join(prefix,
                           self._get_project_id(request),
                           collection_name)
        return "%s?%s" % (url, dict_to_query_str(params))

    def _get_href_link(self, request, identifier, collection_name):
        """Return an href string pointing to this object."""
        prefix = self._update_compute_link_prefix(request.application_url)
        return os.path.join(prefix,
                            self._get_project_id(request),
                            collection_name,
                            str(identifier))

    def _get_bookmark_link(self, request, identifier, collection_name):
        """Create a URL that refers to a specific resource."""
        base_url = remove_version_from_href(request.application_url)
        base_url = self._update_compute_link_prefix(base_url)
        return os.path.join(base_url,
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
        2) 'limit' param is specified but it exceeds CONF.osapi_max_limit,
        in this case the number of items is CONF.osapi_max_limit.
        3) 'limit' param is NOT specified but the number of items is
        CONF.osapi_max_limit.
        """
        links = []
        max_items = min(
            int(request.params.get("limit", CONF.osapi_max_limit)),
            CONF.osapi_max_limit)
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
        return urlparse.urlunsplit(url_parts)

    def _update_glance_link_prefix(self, orig_url):
        return self._update_link_prefix(orig_url,
                                        CONF.osapi_glance_link_prefix)

    def _update_compute_link_prefix(self, orig_url):
        return self._update_link_prefix(orig_url,
                                        CONF.osapi_compute_link_prefix)


def get_instance(compute_api, context, instance_id, want_objects=False,
                 expected_attrs=None):
    """Fetch an instance from the compute API, handling error checking."""
    try:
        return compute_api.get(context, instance_id,
                               want_objects=want_objects,
                               expected_attrs=expected_attrs)
    except exception.InstanceNotFound as e:
        raise exc.HTTPNotFound(explanation=e.format_message())


def check_cells_enabled(function):
    @functools.wraps(function)
    def inner(*args, **kwargs):
        if not CONF.cells.enable:
            msg = _("Cells is not enabled.")
            raise webob.exc.HTTPNotImplemented(explanation=msg)
        return function(*args, **kwargs)
    return inner
