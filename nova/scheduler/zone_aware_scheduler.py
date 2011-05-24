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

"""
The Zone Aware Scheduler is a base class Scheduler for creating instances
across zones. There are two expansion points to this class for:
1. Assigning Weights to hosts for requested instances
2. Filtering Hosts based on required instance capabilities
"""

import operator
import json
import M2Crypto

from nova import crypto
from nova import db
from nova import flags
from nova import log as logging
from nova import rpc

from nova.scheduler import api
from nova.scheduler import driver

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.scheduler.zone_aware_scheduler')


class ZoneAwareScheduler(driver.Scheduler):
    """Base class for creating Zone Aware Schedulers."""

    def _call_zone_method(self, context, method, specs):
        """Call novaclient zone method. Broken out for testing."""
        return api.call_zone_method(context, method, specs=specs)

    def schedule_run_instance(self, context, instance_id, request_spec,
                                        *args, **kwargs):
        """This method is called from nova.compute.api to provision
        an instance. However we need to look at the parameters being
        passed in to see if this is a request to:
        1. Create a Build Plan and then provision, or
        2. Use the Build Plan information in the request parameters
           to simply create the instance (either in this zone or
           a child zone)."""

        # TODO(sandy): We'll have to look for richer specs at some point.

        blob = request_spec['blob']
        if blob:
            self.provision_resource(context, request_spec, instance_id,
                                    request_spec, kwargs)
            return None

        # Create build plan and provision ...
        build_plan = self.select(context, request_spec)
        if not build_plan:
            raise driver.NoValidHost(_('No hosts were available'))

        for item in build_plan:
            self.provision_resource(context, item, instance_id, request_spec,
                                    kwargs)

        # Returning None short-circuits the routing to Compute (since
        # we've already done it here)
        return None

    def provision_resource(self, context, item, instance_id, request_spec,
                           kwargs):
        """Create the requested resource in this Zone or a child zone."""
        if "hostname" in item:
            self._provision_resource_locally(context, item, instance_id,
                            kwargs)
            return
        
        self._provision_resource_in_child_zone(context, item, instance_id,
                                               request_spec, kwargs)

    def _provision_resource_locally(self, context, item, instance_id, kwargs):
        """Create the requested resource in this Zone."""
        host = item['hostname']
        kwargs['instance_id'] = instance_id
        rpc.cast(context,
                 db.queue_get_for(context, "compute", host),
                 {"method": "run_instance",
                  "args": kwargs})
        LOG.debug(_("Casted to compute %(host)s for run_instance")
                            % locals())

    def _provision_resource_in_child_zone(self, context, item, instance_id,
                                          request_spec, kwargs):
        """Create the requested resource in a child zone."""
        # Start by attempting to decrypt the blob to see if this
        # request is:
        # 1. valid, 
        # 2. intended for this zone or a child zone.
        # if 2 ... forward call to child zone.
        LOG.debug(_("****** PROVISION IN CHILD %(item)s") % locals())

        blob = item['blob']
        decryptor = crypto.decryptor(FLAGS.build_plan_encryption_key)
        host_info = None
        try:
            json_entry = decryptor(blob)
            host_info = json.dumps(entry)
        except M2Crypto.EVP.EVPError:
            pass

        if not host_info:
            raise exception.Invalid(_("Ill-formed or incorrectly "
                            "routed 'blob' data sent "
                            "to instance create request.") % locals())

        # Valid data ... is it for us?
        if 'child_zone' in host_info and 'child_blob' in host_info:
            self._ask_child_zone_to_create_instance(context, host_info,
                                                    request_spec, kwargs)
        else:
            self._provision_resource_locally(context, host_info,
                                             instance_id, kwargs)

    def _ask_child_zone_to_create_instance(self, zone_info, request_spec,
                                           kwargs):

        # Note: we have to reverse engineer from our args to get back the
        # image, flavor, ipgroup, etc. since the original call could have
        # come in from EC2 (which doesn't use these things).
        instance_type = request_spec['instance_type']
        instance_properties = request_spec['instance_properties']

        name = instance_properties['display_name']
        image_id = instance_properties['image_id']
        flavor_id = instance_type['flavor_id']
        meta = instance_type['metadata']

        files = kwargs['injected_files']
        ipgroup = None  # Not supported in OS API ... yet
        
        child_zone = zone_info['child_zone']
        child_blob = zone_info['child_blob']
        zone = db.zone_get(child_zone)
        url = zone.api_url
        nova = None
        try:
            nova = novaclient.OpenStack(zone.username, zone.password, url)
            nova.authenticate()
        except novaclient.exceptions.BadRequest, e:
             raise exception.NotAuthorized(_("Bad credentials attempting "
                            "to talk to zone at %(url)s.") % locals())
                            
        nova.servers.create(name, image, flavor, ipgroup, meta, files,
                            child_blob)
        
    def select(self, context, request_spec, *args, **kwargs):
        """Select returns a list of weights and zone/host information
        corresponding to the best hosts to service the request. Any
        child zone information has been encrypted so as not to reveal
        anything about the children."""
        return self._schedule(context, "compute", request_spec,
                              *args, **kwargs)

    # TODO(sandy): We're only focused on compute instances right now,
    # so we don't implement the default "schedule()" method required
    # of Schedulers.
    def schedule(self, context, topic, request_spec, *args, **kwargs):
        """The schedule() contract requires we return the one
        best-suited host for this request.
        """
        raise driver.NoValidHost(_('No hosts were available'))

    def _schedule(self, context, topic, request_spec, *args, **kwargs):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """

        if topic != "compute":
            raise NotImplemented(_("Zone Aware Scheduler only understands "
                                   "Compute nodes (for now)"))

        #TODO(sandy): how to infer this from OS API params?
        num_instances = 1

        LOG.debug(_("XXXXXXX - 1 -  _SCHEDULE"))

        # Filter local hosts based on requirements ...
        host_list = self.filter_hosts(num_instances, request_spec)

        LOG.debug(_("XXXXXXX - 2 -  _SCHEDULE"))
        # then weigh the selected hosts.
        # weighted = [{weight=weight, name=hostname}, ...]
        weighted = self.weigh_hosts(num_instances, request_spec, host_list)

        LOG.debug(_("XXXXXXX - 3 -  _SCHEDULE >> %s") % request_spec)
        # Next, tack on the best weights from the child zones ...
        json_spec = json.dumps(request_spec)
        child_results = self._call_zone_method(context, "select",
                specs=json_spec)
        LOG.debug(_("XXXXXXX - 4 -  _SCHEDULE - CHILD RESULTS %(child_results)s") % locals())
        for child_zone, result in child_results:
            for weighting in result:
                # Remember the child_zone so we can get back to
                # it later if needed. This implicitly builds a zone
                # path structure.
                host_dict = {
                        "weight": weighting["weight"],
                        "child_zone": child_zone,
                        "child_blob": weighting["blob"]}
                weighted.append(host_dict)

        LOG.debug(_("XXXXXXX - 4 -  _SCHEDULE"))
        weighted.sort(key=operator.itemgetter('weight'))
        return weighted

    def filter_hosts(self, num, request_spec):
        """Derived classes must override this method and return
           a list of hosts in [(hostname, capability_dict)] format."""
        raise NotImplemented()

    def weigh_hosts(self, num, request_spec, hosts):
        """Derived classes must override this method and return
           a lists of hosts in [{weight, hostname}] format."""
        raise NotImplemented()
