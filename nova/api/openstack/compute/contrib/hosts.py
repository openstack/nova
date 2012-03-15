# Copyright (c) 2011 OpenStack, LLC.
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

"""The hosts admin extension."""

import webob.exc
from xml.dom import minidom
from xml.parsers import expat

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova.scheduler import api as scheduler_api


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
authorize = extensions.extension_authorizer('compute', 'hosts')


class HostIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        def shimmer(obj, do_raise=False):
            # A bare list is passed in; we need to wrap it in a dict
            return dict(hosts=obj)

        root = xmlutil.TemplateElement('hosts', selector=shimmer)
        elem = xmlutil.SubTemplateElement(root, 'host', selector='hosts')
        elem.set('host_name')
        elem.set('service')

        return xmlutil.MasterTemplate(root, 1)


class HostUpdateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        root.set('host')
        root.set('status')
        root.set('maintenance_mode')

        return xmlutil.MasterTemplate(root, 1)


class HostActionTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        root.set('host')
        root.set('power_action')

        return xmlutil.MasterTemplate(root, 1)


class HostShowTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        elem = xmlutil.make_flat_dict('resource', selector='host',
                                      subselector='resource')
        root.append(elem)

        return xmlutil.MasterTemplate(root, 1)


class HostDeserializer(wsgi.XMLDeserializer):
    def default(self, string):
        try:
            node = minidom.parseString(string)
        except expat.ExpatError:
            msg = _("cannot understand XML")
            raise exception.MalformedRequestBody(reason=msg)

        updates = {}
        for child in node.childNodes[0].childNodes:
            updates[child.tagName] = self.extract_text(child)

        return dict(body=updates)


def _list_hosts(req, service=None):
    """Returns a summary list of hosts, optionally filtering
    by service type.
    """
    context = req.environ['nova.context']
    hosts = scheduler_api.get_host_list(context)
    if service:
        hosts = [host for host in hosts
                if host["service"] == service]
    return hosts


def check_host(fn):
    """Makes sure that the host exists."""
    def wrapped(self, req, id, service=None, *args, **kwargs):
        listed_hosts = _list_hosts(req, service)
        hosts = [h["host_name"] for h in listed_hosts]
        if id in hosts:
            return fn(self, req, id, *args, **kwargs)
        else:
            raise exception.HostNotFound(host=id)
    return wrapped


class HostController(object):
    """The Hosts API controller for the OpenStack API."""
    def __init__(self):
        self.api = compute_api.HostAPI()
        super(HostController, self).__init__()

    @wsgi.serializers(xml=HostIndexTemplate)
    def index(self, req):
        authorize(req.environ['nova.context'])
        return {'hosts': _list_hosts(req)}

    @wsgi.serializers(xml=HostUpdateTemplate)
    @wsgi.deserializers(xml=HostDeserializer)
    @check_host
    def update(self, req, id, body):
        authorize(req.environ['nova.context'])
        update_values = {}
        for raw_key, raw_val in body.iteritems():
            key = raw_key.lower().strip()
            val = raw_val.lower().strip()
            if key == "status":
                if val[:6] in ("enable", "disabl"):
                    update_values['status'] = val.startswith("enable")
                else:
                    explanation = _("Invalid status: '%s'") % raw_val
                    raise webob.exc.HTTPBadRequest(explanation=explanation)
            elif key == "maintenance_mode":
                if val not in ['enable', 'disable']:
                    explanation = _("Invalid mode: '%s'") % raw_val
                    raise webob.exc.HTTPBadRequest(explanation=explanation)
                update_values['maintenance_mode'] = val == 'enable'
            else:
                explanation = _("Invalid update setting: '%s'") % raw_key
                raise webob.exc.HTTPBadRequest(explanation=explanation)

        # this is for handling multiple settings at the same time:
        # the result dictionaries are merged in the first one.
        # Note: the 'host' key will always be the same so it's
        # okay that it gets overwritten.
        update_setters = {'status': self._set_enabled_status,
                          'maintenance_mode': self._set_host_maintenance}
        result = {}
        for key, value in update_values.iteritems():
            result.update(update_setters[key](req, id, value))
        return result

    def _set_host_maintenance(self, req, host, mode=True):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        context = req.environ['nova.context']
        LOG.audit(_("Putting host %(host)s in maintenance "
                    "mode %(mode)s.") % locals())
        result = self.api.set_host_maintenance(context, host, mode)
        if result not in ("on_maintenance", "off_maintenance"):
            raise webob.exc.HTTPBadRequest(explanation=result)
        return {"host": host, "maintenance_mode": result}

    def _set_enabled_status(self, req, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        context = req.environ['nova.context']
        state = "enabled" if enabled else "disabled"
        LOG.audit(_("Setting host %(host)s to %(state)s.") % locals())
        result = self.api.set_host_enabled(context, host=host,
                enabled=enabled)
        if result not in ("enabled", "disabled"):
            # An error message was returned
            raise webob.exc.HTTPBadRequest(explanation=result)
        return {"host": host, "status": result}

    def _host_power_action(self, req, host, action):
        """Reboots, shuts down or powers up the host."""
        context = req.environ['nova.context']
        authorize(context)
        try:
            result = self.api.host_power_action(context, host=host,
                    action=action)
        except NotImplementedError as e:
            raise webob.exc.HTTPBadRequest(explanation=e.msg)
        return {"host": host, "power_action": result}

    @wsgi.serializers(xml=HostActionTemplate)
    def startup(self, req, id):
        return self._host_power_action(req, host=id, action="startup")

    @wsgi.serializers(xml=HostActionTemplate)
    def shutdown(self, req, id):
        return self._host_power_action(req, host=id, action="shutdown")

    @wsgi.serializers(xml=HostActionTemplate)
    def reboot(self, req, id):
        return self._host_power_action(req, host=id, action="reboot")

    @wsgi.serializers(xml=HostShowTemplate)
    def show(self, req, id):
        """Shows the physical/usage resource given by hosts.

        :param context: security context
        :param host: hostname
        :returns: expected to use HostShowTemplate.
            ex.::

                {'host': {'resource':D},..}
                D: {'host': 'hostname','project': 'admin',
                    'cpu': 1, 'memory_mb': 2048, 'disk_gb': 30}
        """
        host = id
        context = req.environ['nova.context']
        # Expected to use AuthMiddleware.
        # Otherwise, non-admin user can use describe-resource
        if not context.is_admin:
            msg = _("Describe-resource is admin only functionality")
            raise webob.exc.HTTPForbidden(explanation=msg)

        # Getting compute node info and related instances info
        try:
            compute_ref = db.service_get_all_compute_by_host(context, host)
            compute_ref = compute_ref[0]
        except exception.ComputeHostNotFound:
            raise webob.exc.HTTPNotFound(explanation=_("Host not found"))
        instance_refs = db.instance_get_all_by_host(context,
                                                    compute_ref['host'])

        # Getting total available/used resource
        compute_ref = compute_ref['compute_node'][0]
        resources = [{'resource': {'host': host, 'project': '(total)',
                      'cpu': compute_ref['vcpus'],
                      'memory_mb': compute_ref['memory_mb'],
                      'disk_gb': compute_ref['local_gb']}},
                     {'resource': {'host': host, 'project': '(used_now)',
                      'cpu': compute_ref['vcpus_used'],
                      'memory_mb': compute_ref['memory_mb_used'],
                      'disk_gb': compute_ref['local_gb_used']}}]

        cpu_sum = 0
        mem_sum = 0
        hdd_sum = 0
        for i in instance_refs:
            cpu_sum += i['vcpus']
            mem_sum += i['memory_mb']
            hdd_sum += i['root_gb'] + i['ephemeral_gb']

        resources.append({'resource': {'host': host,
                          'project': '(used_max)',
                          'cpu': cpu_sum,
                          'memory_mb': mem_sum,
                          'disk_gb': hdd_sum}})

        # Getting usage resource per project
        project_ids = [i['project_id'] for i in instance_refs]
        project_ids = list(set(project_ids))
        for project_id in project_ids:
            vcpus = [i['vcpus'] for i in instance_refs
                     if i['project_id'] == project_id]

            mem = [i['memory_mb']  for i in instance_refs
                   if i['project_id'] == project_id]

            disk = [i['root_gb'] + i['ephemeral_gb'] for i in instance_refs
                    if i['project_id'] == project_id]

            resources.append({'resource': {'host': host,
                              'project': project_id,
                              'cpu': reduce(lambda x, y: x + y, vcpus),
                              'memory_mb': reduce(lambda x, y: x + y, mem),
                              'disk_gb': reduce(lambda x, y: x + y, disk)}})

        return {'host': resources}


class Hosts(extensions.ExtensionDescriptor):
    """Admin-only host administration"""

    name = "Hosts"
    alias = "os-hosts"
    namespace = "http://docs.openstack.org/compute/ext/hosts/api/v1.1"
    updated = "2011-06-29T00:00:00+00:00"

    def get_resources(self):
        resources = [extensions.ResourceExtension('os-hosts',
                HostController(),
                collection_actions={'update': 'PUT'},
                member_actions={"startup": "GET", "shutdown": "GET",
                        "reboot": "GET"})]
        return resources
