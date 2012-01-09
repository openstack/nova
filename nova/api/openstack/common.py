# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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
import os
import re
import urlparse

import webob
from xml.dom import minidom

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import vm_states
from nova.compute import task_states
from nova import flags
from nova import ipv6
from nova import log as logging
from nova import quota


LOG = logging.getLogger('nova.api.openstack.common')
FLAGS = flags.FLAGS


XML_NS_V11 = 'http://docs.openstack.org/compute/api/v1.1'


_STATE_MAP = {
    vm_states.ACTIVE: {
        'default': 'ACTIVE',
        task_states.REBOOTING: 'REBOOT',
        task_states.REBOOTING_HARD: 'HARD_REBOOT',
        task_states.UPDATING_PASSWORD: 'PASSWORD',
        task_states.RESIZE_VERIFY: 'VERIFY_RESIZE',
    },
    vm_states.BUILDING: {
        'default': 'BUILD',
    },
    vm_states.REBUILDING: {
        'default': 'REBUILD',
    },
    vm_states.STOPPED: {
        'default': 'STOPPED',
    },
    vm_states.MIGRATING: {
        'default': 'MIGRATING',
    },
    vm_states.RESIZING: {
        'default': 'RESIZE',
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
    vm_states.SOFT_DELETE: {
        'default': 'DELETED',
    },
}


def status_from_state(vm_state, task_state='default'):
    """Given vm_state and task_state, return a status string."""
    task_map = _STATE_MAP.get(vm_state, dict(default='UNKNOWN_STATE'))
    status = task_map.get(task_state, task_map['default'])
    LOG.debug("Generated %(status)s from vm_state=%(vm_state)s "
              "task_state=%(task_state)s." % locals())
    return status


def vm_state_from_status(status):
    """Map the server status string to a vm state."""
    for state, task_map in _STATE_MAP.iteritems():
        status_string = task_map.get("default")
        if status.lower() == status_string.lower():
            return state


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
        params['limit'] = _get_limit_param(request)
    if 'marker' in request.GET:
        params['marker'] = _get_marker_param(request)
    return params


def _get_limit_param(request):
    """Extract integer limit from request or fail"""
    try:
        limit = int(request.GET['limit'])
    except ValueError:
        msg = _('limit param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)
    if limit < 0:
        msg = _('limit param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)
    return limit


def _get_marker_param(request):
    """Extract marker id from request or fail"""
    return request.GET['marker']


def limited(items, request, max_limit=FLAGS.osapi_max_limit):
    """
    Return a slice of items according to requested offset and limit.

    @param items: A sliceable entity
    @param request: `wsgi.Request` possibly containing 'offset' and 'limit'
                    GET variables. 'offset' is where to start in the list,
                    and 'limit' is the maximum number of items to return. If
                    'limit' is not specified, 0, or > max_limit, we default
                    to max_limit. Negative values for either offset or limit
                    will cause exc.HTTPBadRequest() exceptions to be raised.
    @kwarg max_limit: The maximum number of items to return from 'items'
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


def limited_by_marker(items, request, max_limit=FLAGS.osapi_max_limit):
    """Return a slice of items according to the requested marker and limit."""
    params = get_pagination_params(request)

    limit = params.get('limit', max_limit)
    marker = params.get('marker')

    limit = min(max_limit, limit)
    start_index = 0
    if marker:
        start_index = -1
        for i, item in enumerate(items):
            if item['id'] == marker or item.get('uuid') == marker:
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


def get_version_from_href(href):
    """Returns the api version in the href.

    Returns the api version in the href.
    If no version is found, 1.0 is returned

    Given: 'http://www.nova.com/123'
    Returns: '1.0'

    Given: 'http://www.nova.com/v1.1'
    Returns: '1.1'

    """
    try:
        expression = r'/v([0-9]+|[0-9]+\.[0-9]+)(/|$)'
        return re.findall(expression, href)[0][0]
    except IndexError:
        return '2'


def check_img_metadata_quota_limit(context, metadata):
    if metadata is None:
        return
    num_metadata = len(metadata)
    quota_metadata = quota.allowed_metadata_items(context, num_metadata)
    if quota_metadata < num_metadata:
        expl = _("Image metadata limit exceeded")
        raise webob.exc.HTTPRequestEntityTooLarge(explanation=expl,
                                                headers={'Retry-After': 0})


def dict_to_query_str(params):
    # TODO: we should just use urllib.urlencode instead of this
    # But currently we don't work with urlencoded url's
    param_str = ""
    for key, val in params.iteritems():
        param_str = param_str + '='.join([str(key), str(val)]) + '&'

    return param_str.rstrip('&')


def get_networks_for_instance(context, instance):
    """Returns a prepared nw_info list for passing into the view
    builders

    We end up with a data structure like:
    {'public': {'ips': [{'addr': '10.0.0.1', 'version': 4},
                        {'addr': '2001::1', 'version': 6}],
                'floating_ips': [{'addr': '172.16.0.1', 'version': 4},
                                 {'addr': '172.16.2.1', 'version': 4}]},
     ...}
    """

    def _emit_addr(ip, version):
        return {'addr': ip, 'version': version}

    networks = {}
    fixed_ips = instance['fixed_ips']
    ipv6_addrs_seen = {}
    for fixed_ip in fixed_ips:
        fixed_addr = fixed_ip['address']
        network = fixed_ip['network']
        vif = fixed_ip.get('virtual_interface')
        if not network or not vif:
            name = instance['name']
            ip = fixed_ip['address']
            LOG.warn(_("Instance %(name)s has stale IP "
                    "address: %(ip)s (no network or vif)") % locals())
            continue
        label = network.get('label', None)
        if label is None:
            continue
        if label not in networks:
            networks[label] = {'ips': [], 'floating_ips': []}
        nw_dict = networks[label]
        cidr_v6 = network.get('cidr_v6')
        if FLAGS.use_ipv6 and cidr_v6:
            ipv6_addr = ipv6.to_global(cidr_v6, vif['address'],
                    network['project_id'])
            # Only add same IPv6 address once.  It's possible we've
            # seen it before if there was a previous fixed_ip with
            # same network and vif as this one
            if not ipv6_addrs_seen.get(ipv6_addr):
                nw_dict['ips'].append(_emit_addr(ipv6_addr, 6))
                ipv6_addrs_seen[ipv6_addr] = True
        nw_dict['ips'].append(_emit_addr(fixed_addr, 4))
        for floating_ip in fixed_ip.get('floating_ips', []):
            float_addr = floating_ip['address']
            nw_dict['floating_ips'].append(_emit_addr(float_addr, 4))
    return networks


class MetadataDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = minidom.parseString(text)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}


class MetaItemDeserializer(wsgi.MetadataXMLDeserializer):
    def deserialize(self, text):
        dom = minidom.parseString(text)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


class MetadataXMLDeserializer(wsgi.XMLDeserializer):

    def extract_metadata(self, metadata_node):
        """Marshal the metadata attribute of a parsed request"""
        if metadata_node is None:
            return {}
        metadata = {}
        for meta_node in self.find_children_named(metadata_node, "meta"):
            key = meta_node.getAttribute("key")
            metadata[key] = self.extract_text(meta_node)
        return metadata

    def _extract_metadata_container(self, datastring):
        dom = minidom.parseString(datastring)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}

    def create(self, datastring):
        return self._extract_metadata_container(datastring)

    def update_all(self, datastring):
        return self._extract_metadata_container(datastring)

    def update(self, datastring):
        dom = minidom.parseString(datastring)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


class MetadataHeadersSerializer(wsgi.ResponseHeadersSerializer):

    def delete(self, response, data):
        response.status_int = 204


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


class MetadataXMLSerializer(xmlutil.XMLTemplateSerializer):
    def index(self):
        return MetadataTemplate()

    def create(self):
        return MetadataTemplate()

    def update_all(self):
        return MetadataTemplate()

    def show(self):
        return MetaItemTemplate()

    def update(self):
        return MetaItemTemplate()

    def default(self):
        return xmlutil.MasterTemplate(None, 1)


def check_snapshots_enabled(f):
    @functools.wraps(f)
    def inner(*args, **kwargs):
        if not FLAGS.allow_instance_snapshots:
            LOG.warn(_('Rejecting snapshot request, snapshots currently'
                       ' disabled'))
            msg = _("Instance snapshots are not permitted at this time.")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        return f(*args, **kwargs)
    return inner


class ViewBuilder(object):
    """Model API responses as dictionaries."""

    _collection_name = None

    def _get_links(self, request, identifier):
        return [{
            "rel": "self",
            "href": self._get_href_link(request, identifier),
        },
        {
            "rel": "bookmark",
            "href": self._get_bookmark_link(request, identifier),
        }]

    def _get_next_link(self, request, identifier):
        """Return href string with proper limit and marker params."""
        params = request.params.copy()
        params["marker"] = identifier
        url = os.path.join(request.application_url,
                           request.environ["nova.context"].project_id,
                           self._collection_name)
        return "%s?%s" % (url, dict_to_query_str(params))

    def _get_href_link(self, request, identifier):
        """Return an href string pointing to this object."""
        return os.path.join(request.application_url,
                            request.environ["nova.context"].project_id,
                            self._collection_name,
                            str(identifier))

    def _get_bookmark_link(self, request, identifier):
        """Create a URL that refers to a specific resource."""
        base_url = remove_version_from_href(request.application_url)
        return os.path.join(base_url,
                            request.environ["nova.context"].project_id,
                            self._collection_name,
                            str(identifier))

    def _get_collection_links(self, request, items):
        """Retrieve 'next' link, if applicable."""
        links = []
        limit = int(request.params.get("limit", 0))
        if limit and limit == len(items):
            last_item = items[-1]
            last_item_id = last_item.get("uuid", last_item["id"])
            links.append({
                "rel": "next",
                "href": self._get_next_link(request, last_item_id),
            })
        return links
