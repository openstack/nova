# Copyright 2011 OpenStack Foundation
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

import six
from webob import exc

from oslo.config import cfg

from nova.api.openstack.compute import ips
from nova.api.openstack.compute.servers import ActionDeserializer
from nova.api.openstack.compute.servers import FullServerTemplate

from nova.api.openstack import extensions
from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova import quota
from nova.api.openstack import common
from nova.api.openstack.compute.views import servers as views_servers
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova.compute import flavors
from nova import exception
from nova.image import glance
from nova.objects import block_device as block_device_obj
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import strutils
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import policy
from nova import utils


CONF = cfg.CONF
CONF.import_opt('enable_instance_password',
                'nova.api.openstack.compute.servers')
CONF.import_opt('network_api_class', 'nova.network')
CONF.import_opt('reclaim_instance_interval', 'nova.compute.manager')
CONF.import_opt('extensions_blacklist', 'nova.api.openstack', group='osapi_v3')
CONF.import_opt('extensions_whitelist', 'nova.api.openstack', group='osapi_v3')

LOG = logging.getLogger(__name__)
authorizer = extensions.core_authorizer('compute:v3', 'domains')


def make_server(elem, detailed=False):
    elem.set('name')
    elem.set('id')

    if detailed:
        elem.set('userId', 'user_id')
        elem.set('tenantId', 'tenant_id')
        elem.set('updated')
        elem.set('created')
        elem.set('hostId')
        elem.set('accessIPv4')
        elem.set('accessIPv6')
        elem.set('status')
        elem.set('progress')
        elem.set('reservation_id')

        # Attach image node
        image = xmlutil.SubTemplateElement(elem, 'image', selector='image')
        image.set('id')
        xmlutil.make_links(image, 'links')

        # Attach flavor node
        flavor = xmlutil.SubTemplateElement(elem, 'flavor', selector='flavor')
        flavor.set('id')
        xmlutil.make_links(flavor, 'links')

        # Attach fault node
        make_fault(elem)

        # Attach metadata node
        elem.append(common.MetadataTemplate())

        # Attach addresses node
        elem.append(ips.AddressesTemplate())

    xmlutil.make_links(elem, 'links')


def make_fault(elem):
    fault = xmlutil.SubTemplateElement(elem, 'fault', selector='fault')
    fault.set('code')
    fault.set('created')
    msg = xmlutil.SubTemplateElement(fault, 'message')
    msg.text = 'message'
    det = xmlutil.SubTemplateElement(fault, 'details')
    det.text = 'details'


server_nsmap = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}


class ServerTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root, detailed=True)
        return xmlutil.MasterTemplate(root, 1, nsmap=server_nsmap)


class DomainsController(wsgi.Controller):

    _view_builder_class = views_servers.ViewBuilder

    def __init__(self, ext_mgr=None, **kwargs):
        super(DomainsController, self).__init__(**kwargs)
        self.compute_api = compute.API()
        self.ext_mgr = ext_mgr

    def index_domain(self, req):
        """Returns a list of server names and ids for a given user."""
        try:
            servers = self._get_servers_domain(req, is_detail=False)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        return servers

    @wsgi.serializers(xml=ServerTemplate)
    def show(self, req, server_id):
        """Returns server details by server id."""
        try:
            context = req.environ['nova.context']
            instance = self.compute_api.get(context, server_id,
                                            want_objects=True)
            req.cache_db_instance(instance)
            return self._view_builder.show(req, instance)
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)

    def detail_domain(self, req):
        """Returns a list of server details for a given user."""
        try:
            servers = self._get_servers_domain(req, is_detail=True)
        except exception.Invalid as err:
            raise exc.HTTPBadRequest(explanation=err.format_message())
        return servers

    def _get_servers_domain(self, req, is_detail):
        """Returns a list of servers, based on a given domain."""

        search_opts = {}
        search_opts.update(req.GET)

        context = req.environ['nova.context']
        remove_invalid_options(context, search_opts,
                self._get_server_search_options())

        # Verify search by 'status' contains a valid status.
        # Convert it to filter by vm_state or task_state for compute_api.
        status = search_opts.pop('status', None)
        if status is not None:
            vm_state, task_state = common.task_and_vm_state_from_status(status)
            if not vm_state and not task_state:
                return {'servers': []}
            search_opts['vm_state'] = vm_state
            # When we search by vm state, task state will return 'default'.
            # So we don't need task_state search_opt.
            if 'default' not in task_state:
                search_opts['task_state'] = task_state

        if 'changes_since' in search_opts:
            try:
                parsed = timeutils.parse_isotime(search_opts['changes_since'])
            except ValueError:
                msg = _('Invalid changes_since value')
                raise exc.HTTPBadRequest(explanation=msg)
            search_opts['changes_since'] = parsed

        # By default, compute's get_all() will return deleted instances.
        # If an admin hasn't specified a 'deleted' search option, we need
        # to filter out deleted instances by setting the filter ourselves.
        # ... Unless 'changes_since' is specified, because 'changes_since'
        # should return recently deleted images according to the API spec.

        if 'deleted' not in search_opts:
            if 'changes_since' not in search_opts:
                # No 'changes_since', so we only want non-deleted servers
                search_opts['deleted'] = False

        if 'changes_since' in search_opts:
            search_opts['changes-since'] = search_opts.pop('changes_since')

        if search_opts.get("vm_state") == ['deleted']:
            if context.is_admin:
                search_opts['deleted'] = True
            else:
                msg = _("Only administrators may list deleted instances")
                raise exc.HTTPBadRequest(explanation=msg)

        if context.domain_id:
            search_opts['project_domain_id'] = context.domain_id

        limit, marker = common.get_limit_and_marker(req)
        try:
            instance_list = self.compute_api.get_all(context,
                    search_opts=search_opts, limit=limit, marker=marker,
                    want_objects=True, expected_attrs=['pci_devices'])
        except exception.MarkerNotFound:
            msg = _('marker [%s] not found') % marker
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound:
            log_msg = _("Flavor '%s' could not be found ")
            LOG.debug(log_msg, search_opts['flavor'])
            instance_list = []

        if is_detail:
            instance_list.fill_faults()
            response = self._view_builder.detail(req, instance_list)
        else:
            response = self._view_builder.index(req, instance_list)
        req.cache_db_instances(instance_list)
        return response

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin."""
        return ('reservation_id', 'name', 'status', 'image', 'flavor',
                'ip', 'changes-since', 'all_tenants')

    @wsgi.response(204)
    def delete(self, req, server_id):
        """Destroys a server."""
        try:
            self._delete(req.environ['nova.context'], req, server_id)
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'delete')

    def _delete(self, context, req, instance_uuid):
        instance = self._get_server(context, req, instance_uuid)

        if instance.project_domain_id != context.domain_id:
                raise exc.HTTPNotFound(_("Instance not found."))
        if CONF.reclaim_instance_interval:
            try:
                self.compute_api.soft_delete(context, instance)
            except exception.InstanceInvalidState:
                # Note(yufang521247): instance which has never been active
                # is not allowed to be soft_deleted. Thus we have to call
                # delete() to clean up the instance.
                self.compute_api.delete(context, instance)
        else:
            self.compute_api.delete(context, instance)

    def _get_server(self, context, req, instance_uuid):
        """Utility function for looking up an instance by uuid."""
        try:
            instance = self.compute_api.get(context, instance_uuid,
                                            want_objects=True)
        except exception.NotFound:
            msg = _("Instance could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        req.cache_db_instance(instance)
        return instance

    @wsgi.response(202)
    @wsgi.serializers(xml=FullServerTemplate)
    @wsgi.deserializers(xml=ActionDeserializer)
    @wsgi.action('reboot')
    def _action_reboot(self, req, id, body):
        if 'reboot' in body and 'type' in body['reboot']:
            if not isinstance(body['reboot']['type'], six.string_types):
                msg = _("Argument 'type' for reboot must be a string")
                LOG.error(msg)
                raise exc.HTTPBadRequest(explanation=msg)
            valid_reboot_types = ['HARD', 'SOFT']
            reboot_type = body['reboot']['type'].upper()
            if not valid_reboot_types.count(reboot_type):
                msg = _("Argument 'type' for reboot is not HARD or SOFT")
                LOG.error(msg)
                raise exc.HTTPBadRequest(explanation=msg)
        else:
            msg = _("Missing argument 'type' for reboot")
            LOG.error(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        context = req.environ['nova.context']
        instance = self._get_server(context, req, id)

        try:
            self.compute_api.reboot(context, instance, reboot_type)
        except exception.InstanceIsLocked as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'reboot')
        return webob.Response(status_int=202)


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""
    if context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
                        if opt not in allowed_search_options]
    LOG.debug(_("Removing options '%s' from query"),
              ", ".join(unknown_options))
    for opt in unknown_options:
        search_options.pop(opt, None)


def create_resource(ext_mgr):
    return wsgi.Resource(DomainsController(ext_mgr))
