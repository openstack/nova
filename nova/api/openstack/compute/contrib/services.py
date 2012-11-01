# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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


import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import utils


LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'services')
FLAGS = flags.FLAGS


class ServicesIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('services')
        elem = xmlutil.SubTemplateElement(root, 'service', selector='services')
        elem.set('binary')
        elem.set('host')
        elem.set('zone')
        elem.set('status')
        elem.set('state')
        elem.set('update_at')

        return xmlutil.MasterTemplate(root, 1)


class ServicesUpdateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        root.set('host')
        root.set('service')
        root.set('disabled')

        return xmlutil.MasterTemplate(root, 1)


class ServiceController(object):
    @wsgi.serializers(xml=ServicesIndexTemplate)
    def index(self, req):
        """
        Return a list of all running services. Filter by host & service name.
        """
        context = req.environ['nova.context']
        authorize(context)
        now = timeutils.utcnow()
        services = db.service_get_all(context)

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        service = ''
        if 'service' in req.GET:
            service = req.GET['service']
        if host:
            services = [s for s in services if s['host'] == host]
        if service:
            services = [s for s in services if s['binary'] == service]

        svcs = []
        for svc in services:
            delta = now - (svc['updated_at'] or svc['created_at'])
            alive = abs(utils.total_seconds(delta)) <= FLAGS.service_down_time
            art = (alive and "up") or "down"
            active = 'enabled'
            if svc['disabled']:
                active = 'disabled'
            svcs.append({"binary": svc['binary'], 'host': svc['host'],
                         'zone': svc['availability_zone'],
                         'status': active, 'state': art,
                         'updated_at': svc['updated_at']})
        return {'services': svcs}

    @wsgi.serializers(xml=ServicesUpdateTemplate)
    def update(self, req, id, body):
        """Enable/Disable scheduling for a service"""
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
            service = body['service']
        except (TypeError, KeyError):
            raise webob.exc.HTTPUnprocessableEntity()

        try:
            svc = db.service_get_by_args(context, host, service)
            if not svc:
                raise webob.exc.HTTPNotFound('Unknown service')

            db.service_update(context, svc['id'], {'disabled': disabled})
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound("service not found")

        return {'host': host, 'service': service, 'disabled': disabled}


class Services(extensions.ExtensionDescriptor):
    """Services support"""

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
