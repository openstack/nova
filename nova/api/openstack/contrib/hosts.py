# Copyright (c) 2011 Openstack, LLC.
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

from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.api.openstack.contrib import admin_only
from nova.scheduler import api as scheduler_api


LOG = logging.getLogger("nova.api.hosts")
FLAGS = flags.FLAGS


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
        self.compute_api = compute.API()
        super(HostController, self).__init__()

    def index(self, req):
        return {'hosts': _list_hosts(req)}

    @check_host
    def update(self, req, id, body):
        for raw_key, raw_val in body.iteritems():
            key = raw_key.lower().strip()
            val = raw_val.lower().strip()
            # NOTE: (dabo) Right now only 'status' can be set, but other
            # actions may follow.
            if key == "status":
                if val[:6] in ("enable", "disabl"):
                    return self._set_enabled_status(req, id,
                            enabled=(val.startswith("enable")))
                else:
                    explanation = _("Invalid status: '%s'") % raw_val
                    raise webob.exc.HTTPBadRequest(explanation=explanation)
            elif key == "power_state":
                if val == "startup":
                    # The only valid values for 'state' are 'reboot' or
                    # 'shutdown'. For completeness' sake there is the
                    # 'startup' option to start up a host, but this is not
                    # technically feasible now, as we run the host on the
                    # XenServer box.
                    msg = _("Host startup on XenServer is not supported.")
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                elif val in ("reboot", "shutdown"):
                    return self._set_powerstate(req, id, val)
                else:
                    explanation = _("Invalid powerstate: '%s'") % raw_val
                    raise webob.exc.HTTPBadRequest(explanation=explanation)
            else:
                explanation = _("Invalid update setting: '%s'") % raw_key
                raise webob.exc.HTTPBadRequest(explanation=explanation)

    def _set_enabled_status(self, req, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        context = req.environ['nova.context']
        state = "enabled" if enabled else "disabled"
        LOG.audit(_("Setting host %(host)s to %(state)s.") % locals())
        result = self.compute_api.set_host_enabled(context, host=host,
                enabled=enabled)
        if result not in ("enabled", "disabled"):
            # An error message was returned
            raise webob.exc.HTTPBadRequest(explanation=result)
        return {"host": host, "status": result}

    def _set_powerstate(self, req, host, state):
        """Reboots or shuts down the host."""
        context = req.environ['nova.context']
        result = self.compute_api.set_host_powerstate(context, host=host,
                state=state)
        return {"host": host, "power_state": result}


class Hosts(extensions.ExtensionDescriptor):
    def get_name(self):
        return "Hosts"

    def get_alias(self):
        return "os-hosts"

    def get_description(self):
        return "Host administration"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/hosts/api/v1.1"

    def get_updated(self):
        return "2011-06-29T00:00:00+00:00"

    @admin_only.admin_only
    def get_resources(self):
        resources = []
        # If we are not in an admin env, don't add the resource. Regular users
        # shouldn't have access to the host.
        if FLAGS.allow_admin_api:
            resources = [extensions.ResourceExtension('os-hosts',
                    HostController(), collection_actions={'update': 'PUT'},
                    member_actions={})]
        return resources
