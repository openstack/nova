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
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova import utils


authorize = extensions.extension_authorizer('compute', 'agents')


class AgentController(object):
    """The agent is talking about guest agent.The host can use this for
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
    def index(self, req):
        """Return a list of all agent builds. Filter by hypervisor."""
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(alex_xu): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)
        hypervisor = None
        agents = []
        if 'hypervisor' in req.GET:
            hypervisor = req.GET['hypervisor']

        builds = objects.AgentList.get_all(context, hypervisor=hypervisor)
        for agent_build in builds:
            agents.append({'hypervisor': agent_build.hypervisor,
                           'os': agent_build.os,
                           'architecture': agent_build.architecture,
                           'version': agent_build.version,
                           'md5hash': agent_build.md5hash,
                           'agent_id': agent_build.id,
                           'url': agent_build.url})

        return {'agents': agents}

    def update(self, req, id, body):
        """Update an existing agent build."""
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(alex_xu): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)
        try:
            para = body['para']
            url = para['url']
            md5hash = para['md5hash']
            version = para['version']
        except (TypeError, KeyError) as ex:
            msg = _("Invalid request body: %s") % ex
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            utils.validate_integer(id, 'id')
            utils.check_string_length(url, 'url', max_length=255)
            utils.check_string_length(md5hash, 'md5hash', max_length=255)
            utils.check_string_length(version, 'version', max_length=255)
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            agent = objects.Agent(context=context, id=id)
            agent.obj_reset_changes()
            agent.version = version
            agent.url = url
            agent.md5hash = md5hash
            agent.save()
        except exception.AgentBuildNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

        # NOTE(alex_xu): The agent_id should be integer that consistent with
        # create/index actions. But parameter 'id' is string type that parsed
        # from url. This is a bug, but because back-compatibility, it can't be
        # fixed for v2 API. This will be fixed in v2.1 API by Microversions in
        # the future. lp bug #1333494
        return {"agent": {'agent_id': id, 'version': version,
                'url': url, 'md5hash': md5hash}}

    def delete(self, req, id):
        """Deletes an existing agent build."""
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(alex_xu): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)
        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            agent = objects.Agent(context=context, id=id)
            agent.destroy()
        except exception.AgentBuildNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

    def create(self, req, body):
        """Creates a new agent build."""
        context = req.environ['nova.context']
        authorize(context)
        # NOTE(alex_xu): back-compatible with db layer hard-code admin
        # permission checks.
        nova_context.require_admin_context(context)
        try:
            agent = body['agent']
            hypervisor = agent['hypervisor']
            os = agent['os']
            architecture = agent['architecture']
            version = agent['version']
            url = agent['url']
            md5hash = agent['md5hash']
        except (TypeError, KeyError) as ex:
            msg = _("Invalid request body: %s") % ex
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            utils.check_string_length(hypervisor, 'hypervisor', max_length=255)
            utils.check_string_length(os, 'os', max_length=255)
            utils.check_string_length(architecture, 'architecture',
                                      max_length=255)
            utils.check_string_length(version, 'version', max_length=255)
            utils.check_string_length(url, 'url', max_length=255)
            utils.check_string_length(md5hash, 'md5hash', max_length=255)
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            agent_obj = objects.Agent(context=context)
            agent_obj.hypervisor = hypervisor
            agent_obj.os = os
            agent_obj.architecture = architecture
            agent_obj.version = version
            agent_obj.url = url
            agent_obj.md5hash = md5hash
            agent_obj.create()
            agent['agent_id'] = agent_obj.id
        except exception.AgentBuildExists as ex:
            raise webob.exc.HTTPConflict(explanation=ex.format_message())
        return {'agent': agent}


class Agents(extensions.ExtensionDescriptor):
    """Agents support."""

    name = "Agents"
    alias = "os-agents"
    namespace = "http://docs.openstack.org/compute/ext/agents/api/v2"
    updated = "2012-10-28T00:00:00Z"

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('os-agents',
                                                AgentController())
        resources.append(resource)
        return resources
