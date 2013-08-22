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


import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _


ALIAS = "os-agents"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class AgentsIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('agents')
        elem = xmlutil.SubTemplateElement(root, 'agent', selector='agents')
        elem.set('hypervisor')
        elem.set('os')
        elem.set('architecture')
        elem.set('version')
        elem.set('md5hash')
        elem.set('agent_id')
        elem.set('url')

        return xmlutil.MasterTemplate(root, 1)


class AgentController(object):
    """
    The agent is talking about guest agent.The host can use this for
    things like accessing files on the disk, configuring networking,
    or running other applications/scripts in the guest while it is
    running. Typically this uses some hypervisor-specific transport
    to avoid being dependent on a working network configuration.
    Xen, VMware, and VirtualBox have guest agents,although the Xen
    driver is the only one with an implementation for managing them
    in openstack. KVM doesn't really have a concept of a guest agent
    (although one could be written).

    You can find the design of agent update in this link:
    http://wiki.openstack.org/AgentUpdate
    and find the code in nova.virt.xenapi.vmops.VMOps._boot_new_instance.
    In this design We need update agent in guest from host, so we need
    some interfaces to update the agent info in host.

    You can find more information about the design of the GuestAgent in
    the following link:
    http://wiki.openstack.org/GuestAgent
    http://wiki.openstack.org/GuestAgentXenStoreCommunication
    """
    @extensions.expected_errors(())
    @wsgi.serializers(xml=AgentsIndexTemplate)
    def index(self, req):
        """
        Return a list of all agent builds. Filter by hypervisor.
        """
        context = req.environ['nova.context']
        authorize(context)
        hypervisor = None
        agents = []
        if 'hypervisor' in req.GET:
            hypervisor = req.GET['hypervisor']

        for agent_build in db.agent_build_get_all(context, hypervisor):
            agents.append({'hypervisor': agent_build.hypervisor,
                           'os': agent_build.os,
                           'architecture': agent_build.architecture,
                           'version': agent_build.version,
                           'md5hash': agent_build.md5hash,
                           'agent_id': agent_build.id,
                           'url': agent_build.url})

        return {'agents': agents}

    @extensions.expected_errors((400, 404))
    def update(self, req, id, body):
        """Update an existing agent build."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            para = body['agent']
            url = para['url']
            md5hash = para['md5hash']
            version = para['version']
        except TypeError as e:
            raise webob.exc.HTTPBadRequest()
        except KeyError as e:
            raise webob.exc.HTTPBadRequest(explanation=_(
                "Could not find %s parameter in the request") % e.args[0])

        try:
            db.agent_build_update(context, id,
                                {'version': version,
                                 'url': url,
                                 'md5hash': md5hash})
        except exception.AgentBuildNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

        return {"agent": {'agent_id': id, 'version': version,
                'url': url, 'md5hash': md5hash}}

    @extensions.expected_errors(404)
    @wsgi.response(204)
    def delete(self, req, id):
        """Deletes an existing agent build."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            db.agent_build_destroy(context, id)
        except exception.AgentBuildNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

    @extensions.expected_errors((400, 409))
    @wsgi.response(201)
    def create(self, req, body):
        """Creates a new agent build."""
        context = req.environ['nova.context']
        authorize(context)

        try:
            agent = body['agent']
            hypervisor = agent['hypervisor']
            os = agent['os']
            architecture = agent['architecture']
            version = agent['version']
            url = agent['url']
            md5hash = agent['md5hash']
        except TypeError as e:
            raise webob.exc.HTTPBadRequest()
        except KeyError as e:
            raise webob.exc.HTTPBadRequest(explanation=_(
                "Could not find %s parameter in the request") % e.args[0])

        try:
            agent_build_ref = db.agent_build_create(context,
                                                {'hypervisor': hypervisor,
                                                 'os': os,
                                                 'architecture': architecture,
                                                 'version': version,
                                                 'url': url,
                                                 'md5hash': md5hash})
            agent['agent_id'] = agent_build_ref.id
        except exception.AgentBuildExists as ex:
            raise webob.exc.HTTPConflict(explanation=ex.format_message())
        return {'agent': agent}


class Agents(extensions.V3APIExtensionBase):
    """Agents support."""

    name = "Agents"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/agents/api/v3"
    version = 1

    def get_resources(self):
        resource = [extensions.ResourceExtension(ALIAS,
                                                AgentController())]
        return resource

    def get_controller_extensions(self):
        """It's an abstract function V3APIExtensionBase and the extension
        will not be loaded without it.
        """
        return []
