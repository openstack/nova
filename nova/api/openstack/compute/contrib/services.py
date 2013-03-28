# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM Corp.
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

from oslo.config import cfg
import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import db
from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import utils

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'services')
CONF = cfg.CONF
CONF.import_opt('service_down_time', 'nova.service')


class ServicesIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('services')
        elem = xmlutil.SubTemplateElement(root, 'service', selector='services')
        elem.set('binary')
        elem.set('host')
        elem.set('zone')
        elem.set('status')
        elem.set('state')
        elem.set('updated_at')

        return xmlutil.MasterTemplate(root, 1)


class ServiceUpdateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('service', selector='service')
        root.set('host')
        root.set('binary')
        root.set('status')

        return xmlutil.MasterTemplate(root, 1)


class ServiceUpdateDeserializer(wsgi.XMLDeserializer):
    def default(self, string):
        node = xmlutil.safe_minidom_parse_string(string)
        service = {}
        service_node = self.find_first_child_named(node, 'service')
        if service_node is None:
            return service
        service['host'] = service_node.getAttribute('host')
        service['binary'] = service_node.getAttribute('binary')

        return dict(body=service)


class ServiceController(object):

    def __init__(self):
        self.host_api = compute.HostAPI()

    @wsgi.serializers(xml=ServicesIndexTemplate)
    def index(self, req):
        """
        Return a list of all running services. Filter by host & service name.
        """
        context = req.environ['nova.context']
        authorize(context)
        now = timeutils.utcnow()
        services = self.host_api.service_get_all(
            context, set_zones=True)

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        binary = ''
        if 'binary' in req.GET:
            binary = req.GET['binary']
        if host:
            services = [s for s in services if s['host'] == host]
        if binary:
            services = [s for s in services if s['binary'] == binary]

        svcs = []
        for svc in services:
            delta = now - (svc['updated_at'] or svc['created_at'])
            alive = abs(utils.total_seconds(delta)) <= CONF.service_down_time
            art = (alive and "up") or "down"
            active = 'enabled'
            if svc['disabled']:
                active = 'disabled'
            svcs.append({"binary": svc['binary'], 'host': svc['host'],
                         'zone': svc['availability_zone'],
                         'status': active, 'state': art,
                         'updated_at': svc['updated_at']})
        return {'services': svcs}

    @wsgi.deserializers(xml=ServiceUpdateDeserializer)
    @wsgi.serializers(xml=ServiceUpdateTemplate)
    def update(self, req, id, body):
        """Enable/Disable scheduling for a service."""
        context = req.environ['nova.context']
        authorize(context)

        if id == "enable":
            disabled = False
        elif id == "disable":
            disabled = True
        else:
            raise webob.exc.HTTPNotFound("Unknown action")
        try:
            host = body['host']
            binary = body['binary']
        except (TypeError, KeyError):
            raise webob.exc.HTTPUnprocessableEntity()

        try:
            svc = db.service_get_by_args(context, host, binary)
            if not svc:
                raise webob.exc.HTTPNotFound('Unknown service')

            db.service_update(context, svc['id'], {'disabled': disabled})
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound("service not found")

        status = id + 'd'
        return {'service': {'host': host, 'binary': binary, 'status': status}}


class Services(extensions.ExtensionDescriptor):
    """Services support."""

    name = "Services"
    alias = "os-services"
    namespace = "http://docs.openstack.org/compute/ext/services/api/v2"
    updated = "2012-10-28T00:00:00-00:00"

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('os-services',
                                                ServiceController())
        resources.append(resource)
        return resources
