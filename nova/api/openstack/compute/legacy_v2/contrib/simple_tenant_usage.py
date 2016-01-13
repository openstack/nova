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

import datetime

import iso8601
from oslo_utils import timeutils
import six
import six.moves.urllib.parse as urlparse
from webob import exc

from nova.api.openstack import extensions
from nova import exception
from nova.i18n import _
from nova import objects

authorize_show = extensions.extension_authorizer('compute',
                                                 'simple_tenant_usage:show')
authorize_list = extensions.extension_authorizer('compute',
                                                 'simple_tenant_usage:list')


def parse_strtime(dstr, fmt):
    try:
        return timeutils.parse_strtime(dstr, fmt)
    except (TypeError, ValueError) as e:
        raise exception.InvalidStrTime(reason=six.text_type(e))


class SimpleTenantUsageController(object):
    def _hours_for(self, instance, period_start, period_stop):
        launched_at = instance.launched_at
        terminated_at = instance.terminated_at
        if terminated_at is not None:
            if not isinstance(terminated_at, datetime.datetime):
                # NOTE(mriedem): Instance object DateTime fields are
                # timezone-aware so convert using isotime.
                terminated_at = timeutils.parse_isotime(terminated_at)

        if launched_at is not None:
            if not isinstance(launched_at, datetime.datetime):
                launched_at = timeutils.parse_isotime(launched_at)

        if terminated_at and terminated_at < period_start:
            return 0
        # nothing if it started after the usage report ended
        if launched_at and launched_at > period_stop:
            return 0
        if launched_at:
            # if instance launched after period_started, don't charge for first
            start = max(launched_at, period_start)
            if terminated_at:
                # if instance stopped before period_stop, don't charge after
                stop = min(period_stop, terminated_at)
            else:
                # instance is still running, so charge them up to current time
                stop = period_stop
            dt = stop - start
            return dt.total_seconds() / 3600.0
        else:
            # instance hasn't launched, so no charge
            return 0

    def _get_flavor(self, context, instance, flavors_cache):
        """Get flavor information from the instance object,
        allowing a fallback to lookup by-id for deleted instances only.
        """
        try:
            return instance.get_flavor()
        except exception.NotFound:
            if not instance.deleted:
                # Only support the fallback mechanism for deleted instances
                # that would have been skipped by migration #153
                raise

        flavor_type = instance.instance_type_id
        if flavor_type in flavors_cache:
            return flavors_cache[flavor_type]

        try:
            flavor_ref = objects.Flavor.get_by_id(context, flavor_type)
            flavors_cache[flavor_type] = flavor_ref
        except exception.FlavorNotFound:
            # can't bill if there is no flavor
            flavor_ref = None

        return flavor_ref

    def _tenant_usages_for_period(self, context, period_start,
                                  period_stop, tenant_id=None, detailed=True):

        instances = objects.InstanceList.get_active_by_window_joined(
                        context, period_start, period_stop, tenant_id,
                        expected_attrs=['flavor'])
        rval = {}
        flavors = {}

        for instance in instances:
            info = {}
            info['hours'] = self._hours_for(instance,
                                            period_start,
                                            period_stop)
            flavor = self._get_flavor(context, instance, flavors)
            if not flavor:
                info['flavor'] = ''
            else:
                info['flavor'] = flavor.name

            info['instance_id'] = instance.uuid
            info['name'] = instance.display_name

            info['memory_mb'] = instance.memory_mb
            info['local_gb'] = instance.root_gb + instance.ephemeral_gb
            info['vcpus'] = instance.vcpus

            info['tenant_id'] = instance.project_id

            # NOTE(mriedem): We need to normalize the start/end times back
            # to timezone-naive so the response doesn't change after the
            # conversion to objects.
            info['started_at'] = timeutils.normalize_time(instance.launched_at)

            info['ended_at'] = (
                timeutils.normalize_time(instance.terminated_at) if
                    instance.terminated_at else None)

            if info['ended_at']:
                info['state'] = 'terminated'
            else:
                info['state'] = instance.vm_state

            now = timeutils.utcnow()

            if info['state'] == 'terminated':
                delta = info['ended_at'] - info['started_at']
            else:
                delta = now - info['started_at']

            info['uptime'] = int(delta.total_seconds())

            if info['tenant_id'] not in rval:
                summary = {}
                summary['tenant_id'] = info['tenant_id']
                if detailed:
                    summary['server_usages'] = []
                summary['total_local_gb_usage'] = 0
                summary['total_vcpus_usage'] = 0
                summary['total_memory_mb_usage'] = 0
                summary['total_hours'] = 0
                summary['start'] = timeutils.normalize_time(period_start)
                summary['stop'] = timeutils.normalize_time(period_stop)
                rval[info['tenant_id']] = summary

            summary = rval[info['tenant_id']]
            summary['total_local_gb_usage'] += info['local_gb'] * info['hours']
            summary['total_vcpus_usage'] += info['vcpus'] * info['hours']
            summary['total_memory_mb_usage'] += (info['memory_mb'] *
                                                 info['hours'])

            summary['total_hours'] += info['hours']
            if detailed:
                summary['server_usages'].append(info)

        return rval.values()

    def _parse_datetime(self, dtstr):
        if not dtstr:
            value = timeutils.utcnow()
        elif isinstance(dtstr, datetime.datetime):
            value = dtstr
        else:
            for fmt in ["%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S.%f",
                        "%Y-%m-%d %H:%M:%S.%f"]:
                try:
                    value = parse_strtime(dtstr, fmt)
                    break
                except exception.InvalidStrTime:
                    pass
            else:
                msg = _("Datetime is in invalid format")
                raise exception.InvalidStrTime(reason=msg)

        # NOTE(mriedem): Instance object DateTime fields are timezone-aware
        # so we have to force UTC timezone for comparing this datetime against
        # instance object fields and still maintain backwards compatibility
        # in the API.
        if value.utcoffset() is None:
            value = value.replace(tzinfo=iso8601.iso8601.Utc())
        return value

    def _get_datetime_range(self, req):
        qs = req.environ.get('QUERY_STRING', '')
        env = urlparse.parse_qs(qs)
        # NOTE(lzyeval): env.get() always returns a list
        period_start = self._parse_datetime(env.get('start', [None])[0])
        period_stop = self._parse_datetime(env.get('end', [None])[0])

        if not period_start < period_stop:
            msg = _("Invalid start time. The start time cannot occur after "
                    "the end time.")
            raise exc.HTTPBadRequest(explanation=msg)

        detailed = env.get('detailed', ['0'])[0] == '1'
        return (period_start, period_stop, detailed)

    def index(self, req):
        """Retrieve tenant_usage for all tenants."""
        context = req.environ['nova.context']

        authorize_list(context)

        try:
            (period_start, period_stop, detailed) = self._get_datetime_range(
                req)
        except exception.InvalidStrTime as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        now = timeutils.parse_isotime(timeutils.utcnow().isoformat())
        if period_stop > now:
            period_stop = now
        usages = self._tenant_usages_for_period(context,
                                                period_start,
                                                period_stop,
                                                detailed=detailed)
        return {'tenant_usages': usages}

    def show(self, req, id):
        """Retrieve tenant_usage for a specified tenant."""
        tenant_id = id
        context = req.environ['nova.context']

        authorize_show(context, {'project_id': tenant_id})

        try:
            (period_start, period_stop, ignore) = self._get_datetime_range(
                req)
        except exception.InvalidStrTime as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        now = timeutils.parse_isotime(timeutils.utcnow().isoformat())
        if period_stop > now:
            period_stop = now
        usage = self._tenant_usages_for_period(context,
                                               period_start,
                                               period_stop,
                                               tenant_id=tenant_id,
                                               detailed=True)
        if len(usage):
            usage = list(usage)[0]
        else:
            usage = {}
        return {'tenant_usage': usage}


class Simple_tenant_usage(extensions.ExtensionDescriptor):
    """Simple tenant usage extension."""

    name = "SimpleTenantUsage"
    alias = "os-simple-tenant-usage"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "os-simple-tenant-usage/api/v1.1")
    updated = "2011-08-19T00:00:00Z"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-simple-tenant-usage',
                                           SimpleTenantUsageController())
        resources.append(res)

        return resources
