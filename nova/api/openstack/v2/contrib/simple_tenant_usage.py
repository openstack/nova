# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from datetime import datetime
import urlparse

import webob

from nova.api.openstack.v2 import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import api
from nova import exception
from nova import flags


FLAGS = flags.FLAGS


def make_usage(elem):
    for subelem_tag in ('tenant_id', 'total_local_gb_usage',
                        'total_vcpus_usage', 'total_memory_mb_usage',
                        'total_hours', 'start', 'stop'):
        subelem = xmlutil.SubTemplateElement(elem, subelem_tag)
        subelem.text = subelem_tag

    server_usages = xmlutil.SubTemplateElement(elem, 'server_usages')
    server_usage = xmlutil.SubTemplateElement(server_usages, 'server_usage',
                                              selector='server_usages')
    for subelem_tag in ('name', 'hours', 'memory_mb', 'local_gb', 'vcpus',
                        'tenant_id', 'flavor', 'started_at', 'ended_at',
                        'state', 'uptime'):
        subelem = xmlutil.SubTemplateElement(server_usage, subelem_tag)
        subelem.text = subelem_tag


class SimpleTenantUsageTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('tenant_usage', selector='tenant_usage')
        make_usage(root)
        return xmlutil.MasterTemplate(root, 1)


class SimpleTenantUsagesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('tenant_usages')
        elem = xmlutil.SubTemplateElement(root, 'tenant_usage',
                                          selector='tenant_usages')
        make_usage(elem)
        return xmlutil.MasterTemplate(root, 1)


class SimpleTenantUsageController(object):
    def _hours_for(self, instance, period_start, period_stop):
        launched_at = instance['launched_at']
        terminated_at = instance['terminated_at']
        if terminated_at is not None:
            if not isinstance(terminated_at, datetime):
                terminated_at = datetime.strptime(terminated_at,
                                                  "%Y-%m-%d %H:%M:%S.%f")

        if launched_at is not None:
            if not isinstance(launched_at, datetime):
                launched_at = datetime.strptime(launched_at,
                                                "%Y-%m-%d %H:%M:%S.%f")

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
            seconds = dt.days * 3600 * 24 + dt.seconds\
                      + dt.microseconds / 100000.0

            return seconds / 3600.0
        else:
            # instance hasn't launched, so no charge
            return 0

    def _tenant_usages_for_period(self, context, period_start,
                                  period_stop, tenant_id=None, detailed=True):

        compute_api = api.API()
        instances = compute_api.get_active_by_window(context,
                                                     period_start,
                                                     period_stop,
                                                     tenant_id)
        from nova import log as logging
        logging.info(instances)
        rval = {}
        flavors = {}

        for instance in instances:
            info = {}
            info['hours'] = self._hours_for(instance,
                                            period_start,
                                            period_stop)
            flavor_type = instance['instance_type_id']

            if not flavors.get(flavor_type):
                try:
                    it_ref = compute_api.get_instance_type(context,
                                                           flavor_type)
                    flavors[flavor_type] = it_ref
                except exception.InstanceTypeNotFound:
                    # can't bill if there is no instance type
                    continue

            flavor = flavors[flavor_type]

            info['name'] = instance['display_name']

            info['memory_mb'] = flavor['memory_mb']
            info['local_gb'] = flavor['local_gb']
            info['vcpus'] = flavor['vcpus']

            info['tenant_id'] = instance['project_id']

            info['flavor'] = flavor['name']

            info['started_at'] = instance['launched_at']

            info['ended_at'] = instance['terminated_at']

            if info['ended_at']:
                info['state'] = 'terminated'
            else:
                info['state'] = instance['vm_state']

            now = datetime.utcnow()

            if info['state'] == 'terminated':
                delta = info['ended_at'] - info['started_at']
            else:
                delta = now - info['started_at']

            info['uptime'] = delta.days * 24 * 60 + delta.seconds

            if not info['tenant_id'] in rval:
                summary = {}
                summary['tenant_id'] = info['tenant_id']
                if detailed:
                    summary['server_usages'] = []
                summary['total_local_gb_usage'] = 0
                summary['total_vcpus_usage'] = 0
                summary['total_memory_mb_usage'] = 0
                summary['total_hours'] = 0
                summary['start'] = period_start
                summary['stop'] = period_stop
                rval[info['tenant_id']] = summary

            summary = rval[info['tenant_id']]
            summary['total_local_gb_usage'] += info['local_gb'] * info['hours']
            summary['total_vcpus_usage'] += info['vcpus'] * info['hours']
            summary['total_memory_mb_usage'] += info['memory_mb']\
                                                * info['hours']

            summary['total_hours'] += info['hours']
            if detailed:
                summary['server_usages'].append(info)

        return rval.values()

    def _parse_datetime(self, dtstr):
        if isinstance(dtstr, datetime):
            return dtstr
        try:
            return datetime.strptime(dtstr, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            try:
                return datetime.strptime(dtstr, "%Y-%m-%dT%H:%M:%S.%f")
            except Exception:
                return datetime.strptime(dtstr, "%Y-%m-%d %H:%M:%S.%f")

    def _get_datetime_range(self, req):
        qs = req.environ.get('QUERY_STRING', '')
        env = urlparse.parse_qs(qs)
        period_start = self._parse_datetime(env.get('start',
                                    [datetime.utcnow().isoformat()])[0])
        period_stop = self._parse_datetime(env.get('end',
                                    [datetime.utcnow().isoformat()])[0])

        detailed = bool(env.get('detailed', False))
        return (period_start, period_stop, detailed)

    @wsgi.serializers(xml=SimpleTenantUsagesTemplate)
    def index(self, req):
        """Retrive tenant_usage for all tenants"""
        context = req.environ['nova.context']

        if not context.is_admin:
            return webob.Response(status_int=403)

        (period_start, period_stop, detailed) = self._get_datetime_range(req)
        usages = self._tenant_usages_for_period(context,
                                                period_start,
                                                period_stop,
                                                detailed=detailed)
        return {'tenant_usages': usages}

    @wsgi.serializers(xml=SimpleTenantUsageTemplate)
    def show(self, req, id):
        """Retrive tenant_usage for a specified tenant"""
        tenant_id = id
        context = req.environ['nova.context']

        if not context.is_admin:
            if tenant_id != context.project_id:
                return webob.Response(status_int=403)

        (period_start, period_stop, ignore) = self._get_datetime_range(req)
        usage = self._tenant_usages_for_period(context,
                                               period_start,
                                               period_stop,
                                               tenant_id=tenant_id,
                                               detailed=True)
        if len(usage):
            usage = usage[0]
        else:
            usage = {}
        return {'tenant_usage': usage}


class Simple_tenant_usage(extensions.ExtensionDescriptor):
    """Simple tenant usage extension"""

    name = "SimpleTenantUsage"
    alias = "os-simple-tenant-usage"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "os-simple-tenant-usage/api/v1.1"
    updated = "2011-08-19T00:00:00+00:00"
    admin_only = True

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-simple-tenant-usage',
                                           SimpleTenantUsageController())
        resources.append(res)

        return resources
