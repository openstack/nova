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

from nova.api.openstack.compute.schemas import agents as schema
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova import objects
from nova.policies import agents as agents_policies
from nova import utils


class AgentController(wsgi.Controller):
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
    @extensions.expected_errors(())
    def index(self, req):
        """Return a list of all agent builds. Filter by hypervisor."""
        context = req.environ['nova.context']
        context.can(agents_policies.BASE_POLICY_NAME)
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

    @extensions.expected_errors((400, 404))
    @validation.schema(schema.update)
    def update(self, req, id, body):
        """Update an existing agent build."""
        context = req.environ['nova.context']
        context.can(agents_policies.BASE_POLICY_NAME)

        # TODO(oomichi): This parameter name "para" is different from the ones
        # of the other APIs. Most other names are resource names like "server"
        # etc. This name should be changed to "agent" for consistent naming
        # with v2.1+microversions.
        para = body['para']

        url = para['url']
        md5hash = para['md5hash']
        version = para['version']

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        agent = objects.Agent(context=context, id=id)
        agent.obj_reset_changes()
        agent.version = version
        agent.url = url
        agent.md5hash = md5hash
        try:
            agent.save()
        except exception.AgentBuildNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

        # TODO(alex_xu): The agent_id should be integer that consistent with
        # create/index actions. But parameter 'id' is string type that parsed
        # from url. This is a bug, but because back-compatibility, it can't be
        # fixed for v2 API. This will be fixed in v2.1 API by Microversions in
        # the future. lp bug #1333494
        return {"agent": {'agent_id': id, 'version': version,
                'url': url, 'md5hash': md5hash}}

    # TODO(oomichi): Here should be 204(No Content) instead of 200 by v2.1
    # +microversions because the resource agent has been deleted completely
    # when returning a response.
    @extensions.expected_errors((400, 404))
    @wsgi.response(200)
    def delete(self, req, id):
        """Deletes an existing agent build."""
        context = req.environ['nova.context']
        context.can(agents_policies.BASE_POLICY_NAME)

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())

        try:
            agent = objects.Agent(context=context, id=id)
            agent.destroy()
        except exception.AgentBuildNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.format_message())

    # TODO(oomichi): Here should be 201(Created) instead of 200 by v2.1
    # +microversions because the creation of a resource agent finishes
    # when returning a response.
    @extensions.expected_errors((400, 409))
    @wsgi.response(200)
    @validation.schema(schema.create)
    def create(self, req, body):
        """Creates a new agent build."""
        context = req.environ['nova.context']
        context.can(agents_policies.BASE_POLICY_NAME)

        agent = body['agent']
        hypervisor = agent['hypervisor']
        os = agent['os']
        architecture = agent['architecture']
        version = agent['version']
        url = agent['url']
        md5hash = agent['md5hash']

        agent_obj = objects.Agent(context=context)
        agent_obj.hypervisor = hypervisor
        agent_obj.os = os
        agent_obj.architecture = architecture
        agent_obj.version = version
        agent_obj.url = url
        agent_obj.md5hash = md5hash

        try:
            agent_obj.create()
            agent['agent_id'] = agent_obj.id
        except exception.AgentBuildExists as ex:
            raise webob.exc.HTTPConflict(explanation=ex.format_message())
        return {'agent': agent}
