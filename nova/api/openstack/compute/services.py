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

from keystoneauth1 import exceptions as ks_exc
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import uuidutils
import six
import webob.exc

from nova.api.openstack import api_version_request
from nova.api.openstack.compute.schemas import services
from nova.api.openstack import wsgi
from nova.api import validation
from nova import availability_zones
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova import objects
from nova.policies import services as services_policies
from nova.scheduler.client import report
from nova import servicegroup
from nova import utils

UUID_FOR_ID_MIN_VERSION = '2.53'
PARTIAL_CONSTRUCT_FOR_CELL_DOWN_MIN_VERSION = '2.69'

LOG = logging.getLogger(__name__)


class ServiceController(wsgi.Controller):

    def __init__(self):
        super(ServiceController, self).__init__()
        self.host_api = compute.HostAPI()
        self.aggregate_api = compute.AggregateAPI()
        self.servicegroup_api = servicegroup.API()
        self.actions = {"enable": self._enable,
                        "disable": self._disable,
                        "disable-log-reason": self._disable_log_reason}
        self._placementclient = None  # Lazy-load on first access.

    @property
    def placementclient(self):
        if self._placementclient is None:
            self._placementclient = report.SchedulerReportClient()
        return self._placementclient

    def _get_services(self, req):
        # The API services are filtered out since they are not RPC services
        # and therefore their state is not reported through the service group
        # API, so they would always be reported as 'down' (see bug 1543625).
        api_services = ('nova-osapi_compute', 'nova-metadata')

        context = req.environ['nova.context']

        cell_down_support = api_version_request.is_supported(
            req, min_version=PARTIAL_CONSTRUCT_FOR_CELL_DOWN_MIN_VERSION)

        _services = [
            s
            for s in self.host_api.service_get_all(context, set_zones=True,
                all_cells=True, cell_down_support=cell_down_support)
            if s['binary'] not in api_services
        ]

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        binary = ''
        if 'binary' in req.GET:
            binary = req.GET['binary']
        if host:
            _services = [s for s in _services if s['host'] == host]
        if binary:
            _services = [s for s in _services if s['binary'] == binary]

        return _services

    def _get_service_detail(self, svc, additional_fields, req,
                            cell_down_support=False):
        # NOTE(tssurya): The below logic returns a minimal service construct
        # consisting of only the host, binary and status fields for the compute
        # services in the down cell.
        if (cell_down_support and 'uuid' not in svc):
            return {'binary': svc.binary,
                    'host': svc.host,
                    'status': "UNKNOWN"}

        alive = self.servicegroup_api.service_is_up(svc)
        state = (alive and "up") or "down"
        active = 'enabled'
        if svc['disabled']:
            active = 'disabled'
        updated_time = self.servicegroup_api.get_updated_time(svc)

        uuid_for_id = api_version_request.is_supported(
            req, min_version=UUID_FOR_ID_MIN_VERSION)

        if 'availability_zone' not in svc:
            # The service wasn't loaded with the AZ so we need to do it here.
            # Yes this looks weird, but set_availability_zones makes a copy of
            # the list passed in and mutates the objects within it, so we have
            # to pull it back out from the resulting copied list.
            svc.availability_zone = (
                availability_zones.set_availability_zones(
                    req.environ['nova.context'],
                    [svc])[0]['availability_zone'])

        service_detail = {'binary': svc['binary'],
                          'host': svc['host'],
                          'id': svc['uuid' if uuid_for_id else 'id'],
                          'zone': svc['availability_zone'],
                          'status': active,
                          'state': state,
                          'updated_at': updated_time,
                          'disabled_reason': svc['disabled_reason']}

        for field in additional_fields:
            service_detail[field] = svc[field]

        return service_detail

    def _get_services_list(self, req, additional_fields=()):
        _services = self._get_services(req)
        cell_down_support = api_version_request.is_supported(req,
            min_version=PARTIAL_CONSTRUCT_FOR_CELL_DOWN_MIN_VERSION)
        return [self._get_service_detail(svc, additional_fields, req,
                cell_down_support=cell_down_support) for svc in _services]

    def _enable(self, body, context):
        """Enable scheduling for a service."""
        return self._enable_disable(body, context, "enabled",
                                    {'disabled': False,
                                     'disabled_reason': None})

    def _disable(self, body, context, reason=None):
        """Disable scheduling for a service with optional log."""
        return self._enable_disable(body, context, "disabled",
                                    {'disabled': True,
                                     'disabled_reason': reason})

    def _disable_log_reason(self, body, context):
        """Disable scheduling for a service with a log."""
        try:
            reason = body['disabled_reason']
        except KeyError:
            msg = _('Missing disabled reason field')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return self._disable(body, context, reason)

    def _enable_disable(self, body, context, status, params_to_update):
        """Enable/Disable scheduling for a service."""
        reason = params_to_update.get('disabled_reason')

        ret_value = {
            'service': {
                'host': body['host'],
                'binary': body['binary'],
                'status': status
            },
        }

        if reason:
            ret_value['service']['disabled_reason'] = reason

        self._update(context, body['host'], body['binary'], params_to_update)
        return ret_value

    def _forced_down(self, body, context):
        """Set or unset forced_down flag for the service"""
        try:
            forced_down = strutils.bool_from_string(body["forced_down"])
        except KeyError:
            msg = _('Missing forced_down field')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        host = body['host']
        binary = body['binary']

        ret_value = {'service': {'host': host,
                                 'binary': binary,
                                 'forced_down': forced_down}}
        self._update(context, host, binary, {"forced_down": forced_down})
        return ret_value

    def _update(self, context, host, binary, payload):
        """Do the actual PUT/update"""
        # If the user tried to perform an action
        # (disable/enable/force down) on a non-nova-compute
        # service, provide a more useful error message.
        if binary != 'nova-compute':
            msg = (_(
                'Updating a %(binary)s service is not supported. Only '
                'nova-compute services can be updated.') % {'binary': binary})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            self.host_api.service_update_by_host_and_binary(
                context, host, binary, payload)
        except (exception.HostBinaryNotFound,
                exception.HostMappingNotFound) as exc:
            raise webob.exc.HTTPNotFound(explanation=exc.format_message())

    def _perform_action(self, req, id, body, actions):
        """Calculate action dictionary dependent on provided fields"""
        context = req.environ['nova.context']

        try:
            action = actions[id]
        except KeyError:
            msg = _("Unknown action")
            raise webob.exc.HTTPNotFound(explanation=msg)

        return action(body, context)

    @wsgi.response(204)
    @wsgi.expected_errors((400, 404, 409))
    def delete(self, req, id):
        """Deletes the specified service."""
        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME % 'delete', target={})

        if api_version_request.is_supported(
                req, min_version=UUID_FOR_ID_MIN_VERSION):
            if not uuidutils.is_uuid_like(id):
                msg = _('Invalid uuid %s') % id
                raise webob.exc.HTTPBadRequest(explanation=msg)
        else:
            try:
                utils.validate_integer(id, 'id')
            except exception.InvalidInput as exc:
                raise webob.exc.HTTPBadRequest(
                    explanation=exc.format_message())

        try:
            service = self.host_api.service_get_by_id(context, id)
            # remove the service from all the aggregates in which it's included
            if service.binary == 'nova-compute':
                # Check to see if there are any instances on this compute host
                # because if there are, we need to block the service (and
                # related compute_nodes record) delete since it will impact
                # resource accounting in Placement and orphan the compute node
                # resource provider.
                num_instances = objects.InstanceList.get_count_by_hosts(
                    context, [service['host']])
                if num_instances:
                    raise webob.exc.HTTPConflict(
                        explanation=_('Unable to delete compute service that '
                                      'is hosting instances. Migrate or '
                                      'delete the instances first.'))

                # Similarly, check to see if the are any in-progress migrations
                # involving this host because if there are we need to block the
                # service delete since we could orphan resource providers and
                # break the ability to do things like confirm/revert instances
                # in VERIFY_RESIZE status.
                compute_nodes = objects.ComputeNodeList.get_all_by_host(
                    context, service.host)
                self._assert_no_in_progress_migrations(
                    context, id, compute_nodes)

                aggrs = self.aggregate_api.get_aggregates_by_host(context,
                                                                  service.host)
                for ag in aggrs:
                    self.aggregate_api.remove_host_from_aggregate(context,
                                                                  ag.id,
                                                                  service.host)
                # remove the corresponding resource provider record from
                # placement for the compute nodes managed by this service;
                # remember that an ironic compute service can manage multiple
                # nodes
                for compute_node in compute_nodes:
                    try:
                        self.placementclient.delete_resource_provider(
                            context, compute_node, cascade=True)
                    except ks_exc.ClientException as e:
                        LOG.error(
                            "Failed to delete compute node resource provider "
                            "for compute node %s: %s",
                            compute_node.uuid, six.text_type(e))
                # remove the host_mapping of this host.
                try:
                    hm = objects.HostMapping.get_by_host(context, service.host)
                    hm.destroy()
                except exception.HostMappingNotFound:
                    # It's possible to startup a nova-compute service and then
                    # delete it (maybe it was accidental?) before mapping it to
                    # a cell using discover_hosts, so we just ignore this.
                    pass
            service.destroy()

        except exception.ServiceNotFound:
            explanation = _("Service %s not found.") % id
            raise webob.exc.HTTPNotFound(explanation=explanation)
        except exception.ServiceNotUnique:
            explanation = _("Service id %s refers to multiple services.") % id
            raise webob.exc.HTTPBadRequest(explanation=explanation)

    @staticmethod
    def _assert_no_in_progress_migrations(context, service_id, compute_nodes):
        """Ensures there are no in-progress migrations on the given nodes.

        :param context: nova auth RequestContext
        :param service_id: id of the Service being deleted
        :param compute_nodes: ComputeNodeList of nodes on a compute service
        :raises: HTTPConflict if there are any in-progress migrations on the
            nodes
        """
        for cn in compute_nodes:
            migrations = (
                objects.MigrationList.get_in_progress_by_host_and_node(
                    context, cn.host, cn.hypervisor_hostname))
            if migrations:
                # Log the migrations for the operator and then raise
                # a 409 error.
                LOG.info('Unable to delete compute service with id %s '
                         'for host %s. There are %i in-progress '
                         'migrations involving the host. Migrations '
                         '(uuid:status): %s',
                         service_id, cn.host, len(migrations),
                         ','.join(['%s:%s' % (mig.uuid, mig.status)
                                   for mig in migrations]))
                raise webob.exc.HTTPConflict(
                    explanation=_(
                        'Unable to delete compute service that has '
                        'in-progress migrations. Complete the '
                        'migrations or delete the instances first.'))

    @validation.query_schema(services.index_query_schema_275, '2.75')
    @validation.query_schema(services.index_query_schema, '2.0', '2.74')
    @wsgi.expected_errors(())
    def index(self, req):
        """Return a list of all running services. Filter by host & service
        name
        """
        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME % 'list', target={})
        if api_version_request.is_supported(req, min_version='2.11'):
            _services = self._get_services_list(req, ['forced_down'])
        else:
            _services = self._get_services_list(req)

        return {'services': _services}

    @wsgi.Controller.api_version('2.1', '2.52')
    @wsgi.expected_errors((400, 404))
    @validation.schema(services.service_update, '2.0', '2.10')
    @validation.schema(services.service_update_v211, '2.11', '2.52')
    def update(self, req, id, body):
        """Perform service update

        Before microversion 2.53, the body contains a host and binary value
        to identify the service on which to perform the action. There is no
        service ID passed on the path, just the action, for example
        PUT /os-services/disable.
        """
        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME % 'update', target={})
        if api_version_request.is_supported(req, min_version='2.11'):
            actions = self.actions.copy()
            actions["force-down"] = self._forced_down
        else:
            actions = self.actions

        return self._perform_action(req, id, body, actions)

    @wsgi.Controller.api_version(UUID_FOR_ID_MIN_VERSION)  # noqa F811
    @wsgi.expected_errors((400, 404))
    @validation.schema(services.service_update_v2_53, UUID_FOR_ID_MIN_VERSION)
    def update(self, req, id, body):
        """Perform service update

        Starting with microversion 2.53, the service uuid is passed in on the
        path of the request to uniquely identify the service record on which to
        perform a given update, which is defined in the body of the request.
        """
        service_id = id
        # Validate that the service ID is a UUID.
        if not uuidutils.is_uuid_like(service_id):
            msg = _('Invalid uuid %s') % service_id
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Validate the request context against the policy.
        context = req.environ['nova.context']
        context.can(services_policies.BASE_POLICY_NAME % 'update', target={})

        # Get the service by uuid.
        try:
            service = self.host_api.service_get_by_id(context, service_id)
            # At this point the context is targeted to the cell that the
            # service was found in so we don't need to do any explicit cell
            # targeting below.
        except exception.ServiceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())

        # Return 400 if service.binary is not nova-compute.
        # Before the earlier PUT handlers were made cells-aware, you could
        # technically disable a nova-scheduler service, although that doesn't
        # really do anything within Nova and is just confusing. Now trying to
        # do that will fail as a nova-scheduler service won't have a host
        # mapping so you'll get a 400. In this new microversion, we close that
        # old gap and make sure you can only enable/disable and set forced_down
        # on nova-compute services since those are the only ones that make
        # sense to update for those operations.
        if service.binary != 'nova-compute':
            msg = (_('Updating a %(binary)s service is not supported. Only '
                     'nova-compute services can be updated.') %
                   {'binary': service.binary})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Now determine the update to perform based on the body. We are
        # intentionally not using _perform_action or the other old-style
        # action functions.
        if 'status' in body:
            # This is a status update for either enabled or disabled.
            if body['status'] == 'enabled':

                # Fail if 'disabled_reason' was requested when enabling the
                # service since those two combined don't make sense.
                if body.get('disabled_reason'):
                    msg = _("Specifying 'disabled_reason' with status "
                            "'enabled' is invalid.")
                    raise webob.exc.HTTPBadRequest(explanation=msg)

                service.disabled = False
                service.disabled_reason = None
            elif body['status'] == 'disabled':
                service.disabled = True
                # The disabled reason is optional.
                service.disabled_reason = body.get('disabled_reason')

        # This is intentionally not an elif, i.e. it's in addition to the
        # status update.
        if 'forced_down' in body:
            service.forced_down = strutils.bool_from_string(
                body['forced_down'], strict=True)

        # Check to see if anything was actually updated since the schema does
        # not define any required fields.
        if not service.obj_what_changed():
            msg = _("No updates were requested. Fields 'status' or "
                    "'forced_down' should be specified.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Now save our updates to the service record in the database.
        self.host_api.service_update(context, service)

        # Return the full service record details.
        additional_fields = ['forced_down']
        return {'service': self._get_service_detail(
            service, additional_fields, req)}
