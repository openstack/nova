# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Quotas for instances, and floating ips."""

import datetime

from oslo.config import cfg

from nova import db
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

LOG = logging.getLogger(__name__)

quota_opts = [
    cfg.IntOpt('quota_instances',
               default=10,
               help='number of instances allowed per project'),
    cfg.IntOpt('quota_cores',
               default=20,
               help='number of instance cores allowed per project'),
    cfg.IntOpt('quota_ram',
               default=50 * 1024,
               help='megabytes of instance ram allowed per project'),
    cfg.IntOpt('quota_floating_ips',
               default=10,
               help='number of floating ips allowed per project'),
    cfg.IntOpt('quota_fixed_ips',
               default=-1,
               help=('number of fixed ips allowed per project (this should be '
                     'at least the number of instances allowed)')),
    cfg.IntOpt('quota_metadata_items',
               default=128,
               help='number of metadata items allowed per instance'),
    cfg.IntOpt('quota_injected_files',
               default=5,
               help='number of injected files allowed'),
    cfg.IntOpt('quota_injected_file_content_bytes',
               default=10 * 1024,
               help='number of bytes allowed per injected file'),
    cfg.IntOpt('quota_injected_file_path_bytes',
               default=255,
               help='number of bytes allowed per injected file path'),
    cfg.IntOpt('quota_security_groups',
               default=10,
               help='number of security groups per project'),
    cfg.IntOpt('quota_security_group_rules',
               default=20,
               help='number of security rules per security group'),
    cfg.IntOpt('quota_key_pairs',
               default=100,
               help='number of key pairs per user'),
    cfg.IntOpt('reservation_expire',
               default=86400,
               help='number of seconds until a reservation expires'),
    cfg.IntOpt('until_refresh',
               default=0,
               help='count of reservations until usage is refreshed'),
    cfg.IntOpt('max_age',
               default=0,
               help='number of seconds between subsequent usage refreshes'),
    cfg.StrOpt('quota_driver',
               default='nova.quota.DbQuotaDriver',
               help='default driver to use for quota checks'),
    ]

CONF = cfg.CONF
CONF.register_opts(quota_opts)


class DbQuotaDriver(object):
    """
    Driver to perform necessary checks to enforce quotas and obtain
    quota information.  The default driver utilizes the local
    database.
    """
    def get_by_project_and_user(self, context, project_id, user_id, resource):
        """Get a specific quota by project and user."""

        return db.quota_get(context, project_id, user_id, resource)

    def get_by_project(self, context, project_id, resource):
        """Get a specific quota by project."""

        return db.quota_get(context, project_id, resource)

    def get_by_class(self, context, quota_class, resource):
        """Get a specific quota by quota class."""

        return db.quota_class_get(context, quota_class, resource)

    def get_defaults(self, context, resources):
        """Given a list of resources, retrieve the default quotas.
        Use the class quotas named `_DEFAULT_QUOTA_NAME` as default quotas,
        if it exists.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        """

        quotas = {}
        default_quotas = db.quota_class_get_default(context)
        for resource in resources.values():
            quotas[resource.name] = default_quotas.get(resource.name,
                                                       resource.default)

        return quotas

    def get_class_quotas(self, context, resources, quota_class,
                         defaults=True):
        """
        Given a list of resources, retrieve the quotas for the given
        quota class.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param quota_class: The name of the quota class to return
                            quotas for.
        :param defaults: If True, the default value will be reported
                         if there is no specific value for the
                         resource.
        """

        quotas = {}
        class_quotas = db.quota_class_get_all_by_name(context, quota_class)
        for resource in resources.values():
            if defaults or resource.name in class_quotas:
                quotas[resource.name] = class_quotas.get(resource.name,
                                                         resource.default)

        return quotas

    def _process_quotas(self, context, resources, project_id, quotas,
                        quota_class=None, defaults=True, usages=None,
                        remains=False):
        modified_quotas = {}
        # Get the quotas for the appropriate class.  If the project ID
        # matches the one in the context, we use the quota_class from
        # the context, otherwise, we use the provided quota_class (if
        # any)
        if project_id == context.project_id:
            quota_class = context.quota_class
        if quota_class:
            class_quotas = db.quota_class_get_all_by_name(context, quota_class)
        else:
            class_quotas = {}

        default_quotas = self.get_defaults(context, resources)

        for resource in resources.values():
            # Omit default/quota class values
            if not defaults and resource.name not in quotas:
                continue

            limit = quotas.get(resource.name, class_quotas.get(
                        resource.name, default_quotas[resource.name]))
            modified_quotas[resource.name] = dict(limit=limit)

            # Include usages if desired.  This is optional because one
            # internal consumer of this interface wants to access the
            # usages directly from inside a transaction.
            if usages:
                usage = usages.get(resource.name, {})
                modified_quotas[resource.name].update(
                    in_use=usage.get('in_use', 0),
                    reserved=usage.get('reserved', 0),
                    )
            # Initialize remains quotas.
            if remains:
                modified_quotas[resource.name].update(remains=limit)

        if remains:
            all_quotas = db.quota_get_all(context, project_id)
            for quota in all_quotas:
                if quota.resource in modified_quotas:
                    modified_quotas[quota.resource]['remains'] -= \
                            quota.hard_limit

        return modified_quotas

    def get_user_quotas(self, context, resources, project_id, user_id,
                        quota_class=None, defaults=True,
                        usages=True):
        """
        Given a list of resources, retrieve the quotas for the given
        user and project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param user_id: The ID of the user to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.  It
                            will be ignored if project_id ==
                            context.project_id.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use and reserved counts
                       will also be returned.
        """
        user_quotas = db.quota_get_all_by_project_and_user(context,
                                                           project_id, user_id)
        # Use the project quota for default user quota.
        proj_quotas = db.quota_get_all_by_project(context, project_id)
        for key, value in proj_quotas.iteritems():
            if key not in user_quotas.keys():
                user_quotas[key] = value
        user_usages = None
        if usages:
            user_usages = db.quota_usage_get_all_by_project_and_user(context,
                                                         project_id,
                                                         user_id)
        return self._process_quotas(context, resources, project_id,
                                    user_quotas, quota_class,
                                    defaults=defaults, usages=user_usages)

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True,
                           usages=True, remains=False):
        """
        Given a list of resources, retrieve the quotas for the given
        project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.  It
                            will be ignored if project_id ==
                            context.project_id.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use and reserved counts
                       will also be returned.
        :param remains: If True, the current remains of the project will
                        will be returned.
        """
        project_quotas = db.quota_get_all_by_project(context, project_id)
        project_usages = None
        if usages:
            project_usages = db.quota_usage_get_all_by_project(context,
                                                               project_id)
        return self._process_quotas(context, resources, project_id,
                                    project_quotas, quota_class,
                                    defaults=defaults, usages=project_usages,
                                    remains=remains)

    def get_settable_quotas(self, context, resources, project_id,
                            user_id=None):
        """
        Given a list of resources, retrieve the range of settable quotas for
        the given user or project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param user_id: The ID of the user to return quotas for.
        """
        settable_quotas = {}
        project_quotas = self.get_project_quotas(context, resources,
                                                 project_id, remains=True)
        if user_id:
            user_quotas = self.get_user_quotas(context, resources,
                                               project_id, user_id)
            setted_quotas = db.quota_get_all_by_project_and_user(context,
                                                     project_id,
                                                     user_id)
            for key, value in user_quotas.items():
                maximum = project_quotas[key]['remains'] +\
                        setted_quotas.get(key, 0)
                settable_quotas[key] = dict(
                        minimum=value['in_use'] + value['reserved'],
                        maximum=maximum
                        )
        else:
            for key, value in project_quotas.items():
                minimum = max(int(value['limit'] - value['remains']),
                              int(value['in_use'] + value['reserved']))
                settable_quotas[key] = dict(minimum=minimum, maximum=-1)
        return settable_quotas

    def _get_quotas(self, context, resources, keys, has_sync, project_id=None,
                    user_id=None):
        """
        A helper method which retrieves the quotas for the specific
        resources identified by keys, and which apply to the current
        context.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param keys: A list of the desired quotas to retrieve.
        :param has_sync: If True, indicates that the resource must
                         have a sync function; if False, indicates
                         that the resource must NOT have a sync
                         function.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """

        # Filter resources
        if has_sync:
            sync_filt = lambda x: hasattr(x, 'sync')
        else:
            sync_filt = lambda x: not hasattr(x, 'sync')
        desired = set(keys)
        sub_resources = dict((k, v) for k, v in resources.items()
                             if k in desired and sync_filt(v))

        # Make sure we accounted for all of them...
        if len(keys) != len(sub_resources):
            unknown = desired - set(sub_resources.keys())
            raise exception.QuotaResourceUnknown(unknown=sorted(unknown))

        if user_id:
            # Grab and return the quotas (without usages)
            quotas = self.get_user_quotas(context, sub_resources,
                                          project_id, user_id,
                                          context.quota_class, usages=False)
        else:
            # Grab and return the quotas (without usages)
            quotas = self.get_project_quotas(context, sub_resources,
                                             project_id,
                                             context.quota_class,
                                             usages=False)

        return dict((k, v['limit']) for k, v in quotas.items())

    def limit_check(self, context, resources, values, project_id=None,
                    user_id=None):
        """Check simple quota limits.

        For limits--those quotas for which there is no usage
        synchronization function--this method checks that a set of
        proposed values are permitted by the limit restriction.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it is not a simple limit
        resource.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns
        nothing.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param values: A dictionary of the values to check against the
                       quota.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """

        # Ensure no value is less than zero
        unders = [key for key, val in values.items() if val < 0]
        if unders:
            raise exception.InvalidQuotaValue(unders=sorted(unders))

        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id
        # If user id is None, then we use the user_id in context
        if user_id is None:
            user_id = context.user_id

        # Get the applicable quotas
        quotas = self._get_quotas(context, resources, values.keys(),
                                  has_sync=False, project_id=project_id)
        user_quotas = self._get_quotas(context, resources, values.keys(),
                                       has_sync=False, project_id=project_id,
                                       user_id=user_id)

        # Check the quotas and construct a list of the resources that
        # would be put over limit by the desired values
        overs = [key for key, val in values.items()
                 if quotas[key] >= 0 and quotas[key] < val or
                 (user_quotas[key] >= 0 and user_quotas[key] < val)]
        if overs:
            headroom = {}
            # Check project_quotas:
            for key in quotas:
                if quotas[key] >= 0 and quotas[key] < val:
                    headroom[key] = quotas[key]
            # Check user quotas:
            for key in user_quotas:
                if (user_quotas[key] >= 0 and user_quotas[key] < val and
                        headroom.get(key) > user_quotas[key]):
                    headroom[key] = user_quotas[key]

            raise exception.OverQuota(overs=sorted(overs), quotas=quotas,
                                      usages={}, headroom=headroom)

    def reserve(self, context, resources, deltas, expire=None,
                project_id=None, user_id=None):
        """Check quotas and reserve resources.

        For counting quotas--those quotas for which there is a usage
        synchronization function--this method checks quotas against
        current usage and the desired deltas.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it does not have a usage
        synchronization function.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns a
        list of reservation UUIDs which were created.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param deltas: A dictionary of the proposed delta changes.
        :param expire: An optional parameter specifying an expiration
                       time for the reservations.  If it is a simple
                       number, it is interpreted as a number of
                       seconds and added to the current time; if it is
                       a datetime.timedelta object, it will also be
                       added to the current time.  A datetime.datetime
                       object will be interpreted as the absolute
                       expiration time.  If None is specified, the
                       default expiration time set by
                       --default-reservation-expire will be used (this
                       value will be treated as a number of seconds).
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """

        # Set up the reservation expiration
        if expire is None:
            expire = CONF.reservation_expire
        if isinstance(expire, (int, long)):
            expire = datetime.timedelta(seconds=expire)
        if isinstance(expire, datetime.timedelta):
            expire = timeutils.utcnow() + expire
        if not isinstance(expire, datetime.datetime):
            raise exception.InvalidReservationExpiration(expire=expire)

        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id
        # If user_id is None, then we use the project_id in context
        if user_id is None:
            user_id = context.user_id

        # Get the applicable quotas.
        # NOTE(Vek): We're not worried about races at this point.
        #            Yes, the admin may be in the process of reducing
        #            quotas, but that's a pretty rare thing.
        quotas = self._get_quotas(context, resources, deltas.keys(),
                                  has_sync=True, project_id=project_id)
        user_quotas = self._get_quotas(context, resources, deltas.keys(),
                                       has_sync=True, project_id=project_id,
                                       user_id=user_id)

        # NOTE(Vek): Most of the work here has to be done in the DB
        #            API, because we have to do it in a transaction,
        #            which means access to the session.  Since the
        #            session isn't available outside the DBAPI, we
        #            have to do the work there.
        return db.quota_reserve(context, resources, quotas, user_quotas,
                                deltas, expire,
                                CONF.until_refresh, CONF.max_age,
                                project_id=project_id, user_id=user_id)

    def commit(self, context, reservations, project_id=None, user_id=None):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """
        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id
        # If user_id is None, then we use the user_id in context
        if user_id is None:
            user_id = context.user_id

        db.reservation_commit(context, reservations, project_id=project_id,
                              user_id=user_id)

    def rollback(self, context, reservations, project_id=None, user_id=None):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """
        # If project_id is None, then we use the project_id in context
        if project_id is None:
            project_id = context.project_id
        # If user_id is None, then we use the user_id in context
        if user_id is None:
            user_id = context.user_id

        db.reservation_rollback(context, reservations, project_id=project_id,
                                user_id=user_id)

    def usage_reset(self, context, resources):
        """
        Reset the usage records for a particular user on a list of
        resources.  This will force that user's usage records to be
        refreshed the next time a reservation is made.

        Note: this does not affect the currently outstanding
        reservations the user has; those reservations must be
        committed or rolled back (or expired).

        :param context: The request context, for access checks.
        :param resources: A list of the resource names for which the
                          usage must be reset.
        """

        # We need an elevated context for the calls to
        # quota_usage_update()
        elevated = context.elevated()

        for resource in resources:
            try:
                # Reset the usage to -1, which will force it to be
                # refreshed
                db.quota_usage_update(elevated, context.project_id,
                                      context.user_id,
                                      resource, in_use=-1)
            except exception.QuotaUsageNotFound:
                # That means it'll be refreshed anyway
                pass

    def destroy_all_by_project_and_user(self, context, project_id, user_id):
        """
        Destroy all quotas, usages, and reservations associated with a
        project and user.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        :param user_id: The ID of the user being deleted.
        """

        db.quota_destroy_all_by_project_and_user(context, project_id, user_id)

    def destroy_all_by_project(self, context, project_id):
        """
        Destroy all quotas, usages, and reservations associated with a
        project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        """

        db.quota_destroy_all_by_project(context, project_id)

    def expire(self, context):
        """Expire reservations.

        Explores all currently existing reservations and rolls back
        any that have expired.

        :param context: The request context, for access checks.
        """

        db.reservation_expire(context)


class NoopQuotaDriver(object):
    """Driver that turns quotas calls into no-ops and pretends that quotas
    for all resources are unlimited.  This can be used if you do not
    wish to have any quota checking.  For instance, with nova compute
    cells, the parent cell should do quota checking, but the child cell
    should not.
    """

    def get_by_project_and_user(self, context, project_id, user_id, resource):
        """Get a specific quota by project and user."""
        # Unlimited
        return -1

    def get_by_project(self, context, project_id, resource):
        """Get a specific quota by project."""
        # Unlimited
        return -1

    def get_by_class(self, context, quota_class, resource):
        """Get a specific quota by quota class."""
        # Unlimited
        return -1

    def get_defaults(self, context, resources):
        """Given a list of resources, retrieve the default quotas.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        """
        quotas = {}
        for resource in resources.values():
            quotas[resource.name] = -1
        return quotas

    def get_class_quotas(self, context, resources, quota_class,
                         defaults=True):
        """
        Given a list of resources, retrieve the quotas for the given
        quota class.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param quota_class: The name of the quota class to return
                            quotas for.
        :param defaults: If True, the default value will be reported
                         if there is no specific value for the
                         resource.
        """
        quotas = {}
        for resource in resources.values():
            quotas[resource.name] = -1
        return quotas

    def get_user_quotas(self, context, resources, project_id, user_id,
                        quota_class=None, defaults=True,
                        usages=True):
        """
        Given a list of resources, retrieve the quotas for the given
        user and project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param user_id: The ID of the user to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.  It
                            will be ignored if project_id ==
                            context.project_id.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use and reserved counts
                       will also be returned.
        """
        quotas = {}
        for resource in resources.values():
            quotas[resource.name] = -1
        return quotas

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True,
                           usages=True, remains=False):
        """
        Given a list of resources, retrieve the quotas for the given
        project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.  It
                            will be ignored if project_id ==
                            context.project_id.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use and reserved counts
                       will also be returned.
        :param remains: If True, the current remains of the project will
                        will be returned.
        """
        quotas = {}
        for resource in resources.values():
            quotas[resource.name] = -1
        return quotas

    def get_settable_quotas(self, context, resources, project_id,
                            user_id=None):
        """
        Given a list of resources, retrieve the range of settable quotas for
        the given user or project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param user_id: The ID of the user to return quotas for.
        """
        quotas = {}
        for resource in resources.values():
            quotas[resource.name].update(minimum=0, maximum=-1)
        return quotas

    def limit_check(self, context, resources, values, project_id=None,
                    user_id=None):
        """Check simple quota limits.

        For limits--those quotas for which there is no usage
        synchronization function--this method checks that a set of
        proposed values are permitted by the limit restriction.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it is not a simple limit
        resource.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns
        nothing.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param values: A dictionary of the values to check against the
                       quota.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """
        pass

    def reserve(self, context, resources, deltas, expire=None,
                project_id=None, user_id=None):
        """Check quotas and reserve resources.

        For counting quotas--those quotas for which there is a usage
        synchronization function--this method checks quotas against
        current usage and the desired deltas.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it does not have a usage
        synchronization function.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns a
        list of reservation UUIDs which were created.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param deltas: A dictionary of the proposed delta changes.
        :param expire: An optional parameter specifying an expiration
                       time for the reservations.  If it is a simple
                       number, it is interpreted as a number of
                       seconds and added to the current time; if it is
                       a datetime.timedelta object, it will also be
                       added to the current time.  A datetime.datetime
                       object will be interpreted as the absolute
                       expiration time.  If None is specified, the
                       default expiration time set by
                       --default-reservation-expire will be used (this
                       value will be treated as a number of seconds).
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """
        return []

    def commit(self, context, reservations, project_id=None, user_id=None):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """
        pass

    def rollback(self, context, reservations, project_id=None, user_id=None):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """
        pass

    def usage_reset(self, context, resources):
        """
        Reset the usage records for a particular user on a list of
        resources.  This will force that user's usage records to be
        refreshed the next time a reservation is made.

        Note: this does not affect the currently outstanding
        reservations the user has; those reservations must be
        committed or rolled back (or expired).

        :param context: The request context, for access checks.
        :param resources: A list of the resource names for which the
                          usage must be reset.
        """
        pass

    def destroy_all_by_project_and_user(self, context, project_id, user_id):
        """
        Destroy all quotas, usages, and reservations associated with a
        project and user.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        :param user_id: The ID of the user being deleted.
        """
        pass

    def destroy_all_by_project(self, context, project_id):
        """
        Destroy all quotas, usages, and reservations associated with a
        project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        """
        pass

    def expire(self, context):
        """Expire reservations.

        Explores all currently existing reservations and rolls back
        any that have expired.

        :param context: The request context, for access checks.
        """
        pass


class BaseResource(object):
    """Describe a single resource for quota checking."""

    def __init__(self, name, flag=None):
        """
        Initializes a Resource.

        :param name: The name of the resource, i.e., "instances".
        :param flag: The name of the flag or configuration option
                     which specifies the default value of the quota
                     for this resource.
        """

        self.name = name
        self.flag = flag

    def quota(self, driver, context, **kwargs):
        """
        Given a driver and context, obtain the quota for this
        resource.

        :param driver: A quota driver.
        :param context: The request context.
        :param project_id: The project to obtain the quota value for.
                           If not provided, it is taken from the
                           context.  If it is given as None, no
                           project-specific quota will be searched
                           for.
        :param quota_class: The quota class corresponding to the
                            project, or for which the quota is to be
                            looked up.  If not provided, it is taken
                            from the context.  If it is given as None,
                            no quota class-specific quota will be
                            searched for.  Note that the quota class
                            defaults to the value in the context,
                            which may not correspond to the project if
                            project_id is not the same as the one in
                            the context.
        """

        # Get the project ID
        project_id = kwargs.get('project_id', context.project_id)

        # Ditto for the quota class
        quota_class = kwargs.get('quota_class', context.quota_class)

        # Look up the quota for the project
        if project_id:
            try:
                return driver.get_by_project(context, project_id, self.name)
            except exception.ProjectQuotaNotFound:
                pass

        # Try for the quota class
        if quota_class:
            try:
                return driver.get_by_class(context, quota_class, self.name)
            except exception.QuotaClassNotFound:
                pass

        # OK, return the default
        return self.default

    @property
    def default(self):
        """Return the default value of the quota."""

        return CONF[self.flag] if self.flag else -1


class ReservableResource(BaseResource):
    """Describe a reservable resource."""

    def __init__(self, name, sync, flag=None):
        """Initializes a ReservableResource.

        Reservable resources are those resources which directly
        correspond to objects in the database, i.e., instances,
        cores, etc.

        Usage synchronization function must be associated with each
        object. This function will be called to determine the current
        counts of one or more resources. This association is done in
        database backend.

        The usage synchronization function will be passed three
        arguments: an admin context, the project ID, and an opaque
        session object, which should in turn be passed to the
        underlying database function.  Synchronization functions
        should return a dictionary mapping resource names to the
        current in_use count for those resources; more than one
        resource and resource count may be returned.  Note that
        synchronization functions may be associated with more than one
        ReservableResource.

        :param name: The name of the resource, i.e., "volumes".
        :param sync: A dbapi methods name which returns a dictionary
                     to resynchronize the in_use count for one or more
                     resources, as described above.
        :param flag: The name of the flag or configuration option
                     which specifies the default value of the quota
                     for this resource.
        """
        super(ReservableResource, self).__init__(name, flag=flag)
        self.sync = sync


class AbsoluteResource(BaseResource):
    """Describe a non-reservable resource."""

    pass


class CountableResource(AbsoluteResource):
    """
    Describe a resource where the counts aren't based solely on the
    project ID.
    """

    def __init__(self, name, count, flag=None):
        """
        Initializes a CountableResource.

        Countable resources are those resources which directly
        correspond to objects in the database, i.e., instances, cores,
        etc., but for which a count by project ID is inappropriate.  A
        CountableResource must be constructed with a counting
        function, which will be called to determine the current counts
        of the resource.

        The counting function will be passed the context, along with
        the extra positional and keyword arguments that are passed to
        Quota.count().  It should return an integer specifying the
        count.

        Note that this counting is not performed in a transaction-safe
        manner.  This resource class is a temporary measure to provide
        required functionality, until a better approach to solving
        this problem can be evolved.

        :param name: The name of the resource, i.e., "instances".
        :param count: A callable which returns the count of the
                      resource.  The arguments passed are as described
                      above.
        :param flag: The name of the flag or configuration option
                     which specifies the default value of the quota
                     for this resource.
        """

        super(CountableResource, self).__init__(name, flag=flag)
        self.count = count


class QuotaEngine(object):
    """Represent the set of recognized quotas."""

    def __init__(self, quota_driver_class=None):
        """Initialize a Quota object."""
        self._resources = {}
        self._driver_cls = quota_driver_class
        self.__driver = None

    @property
    def _driver(self):
        if self.__driver:
            return self.__driver
        if not self._driver_cls:
            self._driver_cls = CONF.quota_driver
        if isinstance(self._driver_cls, basestring):
            self._driver_cls = importutils.import_object(self._driver_cls)
        self.__driver = self._driver_cls
        return self.__driver

    def __contains__(self, resource):
        return resource in self._resources

    def register_resource(self, resource):
        """Register a resource."""

        self._resources[resource.name] = resource

    def register_resources(self, resources):
        """Register a list of resources."""

        for resource in resources:
            self.register_resource(resource)

    def get_by_project_and_user(self, context, project_id, user_id, resource):
        """Get a specific quota by project and user."""

        return self._driver.get_by_project_and_user(context, project_id,
                                                    user_id, resource)

    def get_by_project(self, context, project_id, resource):
        """Get a specific quota by project."""

        return self._driver.get_by_project(context, project_id, resource)

    def get_by_class(self, context, quota_class, resource):
        """Get a specific quota by quota class."""

        return self._driver.get_by_class(context, quota_class, resource)

    def get_defaults(self, context):
        """Retrieve the default quotas.

        :param context: The request context, for access checks.
        """

        return self._driver.get_defaults(context, self._resources)

    def get_class_quotas(self, context, quota_class, defaults=True):
        """Retrieve the quotas for the given quota class.

        :param context: The request context, for access checks.
        :param quota_class: The name of the quota class to return
                            quotas for.
        :param defaults: If True, the default value will be reported
                         if there is no specific value for the
                         resource.
        """

        return self._driver.get_class_quotas(context, self._resources,
                                             quota_class, defaults=defaults)

    def get_user_quotas(self, context, project_id, user_id, quota_class=None,
                        defaults=True, usages=True):
        """Retrieve the quotas for the given user and project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project to return quotas for.
        :param user_id: The ID of the user to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use and reserved counts
                       will also be returned.
        """

        return self._driver.get_user_quotas(context, self._resources,
                                            project_id, user_id,
                                            quota_class=quota_class,
                                            defaults=defaults,
                                            usages=usages)

    def get_project_quotas(self, context, project_id, quota_class=None,
                           defaults=True, usages=True, remains=False):
        """Retrieve the quotas for the given project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project to return quotas for.
        :param quota_class: If project_id != context.project_id, the
                            quota class cannot be determined.  This
                            parameter allows it to be specified.
        :param defaults: If True, the quota class value (or the
                         default value, if there is no value from the
                         quota class) will be reported if there is no
                         specific value for the resource.
        :param usages: If True, the current in_use and reserved counts
                       will also be returned.
        :param remains: If True, the current remains of the project will
                        will be returned.
        """

        return self._driver.get_project_quotas(context, self._resources,
                                              project_id,
                                              quota_class=quota_class,
                                              defaults=defaults,
                                              usages=usages,
                                              remains=remains)

    def get_settable_quotas(self, context, project_id, user_id=None):
        """
        Given a list of resources, retrieve the range of settable quotas for
        the given user or project.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param project_id: The ID of the project to return quotas for.
        :param user_id: The ID of the user to return quotas for.
        """

        return self._driver.get_settable_quotas(context, self._resources,
                                                project_id,
                                                user_id=user_id)

    def count(self, context, resource, *args, **kwargs):
        """Count a resource.

        For countable resources, invokes the count() function and
        returns its result.  Arguments following the context and
        resource are passed directly to the count function declared by
        the resource.

        :param context: The request context, for access checks.
        :param resource: The name of the resource, as a string.
        """

        # Get the resource
        res = self._resources.get(resource)
        if not res or not hasattr(res, 'count'):
            raise exception.QuotaResourceUnknown(unknown=[resource])

        return res.count(context, *args, **kwargs)

    def limit_check(self, context, project_id=None, user_id=None, **values):
        """Check simple quota limits.

        For limits--those quotas for which there is no usage
        synchronization function--this method checks that a set of
        proposed values are permitted by the limit restriction.  The
        values to check are given as keyword arguments, where the key
        identifies the specific quota limit to check, and the value is
        the proposed value.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it is not a simple limit
        resource.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns
        nothing.

        :param context: The request context, for access checks.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        :param user_id: Specify the user_id if current context
                        is admin and admin wants to impact on
                        common user.
        """

        return self._driver.limit_check(context, self._resources, values,
                                        project_id=project_id, user_id=user_id)

    def reserve(self, context, expire=None, project_id=None, user_id=None,
                **deltas):
        """Check quotas and reserve resources.

        For counting quotas--those quotas for which there is a usage
        synchronization function--this method checks quotas against
        current usage and the desired deltas.  The deltas are given as
        keyword arguments, and current usage and other reservations
        are factored into the quota check.

        This method will raise a QuotaResourceUnknown exception if a
        given resource is unknown or if it does not have a usage
        synchronization function.

        If any of the proposed values is over the defined quota, an
        OverQuota exception will be raised with the sorted list of the
        resources which are too high.  Otherwise, the method returns a
        list of reservation UUIDs which were created.

        :param context: The request context, for access checks.
        :param expire: An optional parameter specifying an expiration
                       time for the reservations.  If it is a simple
                       number, it is interpreted as a number of
                       seconds and added to the current time; if it is
                       a datetime.timedelta object, it will also be
                       added to the current time.  A datetime.datetime
                       object will be interpreted as the absolute
                       expiration time.  If None is specified, the
                       default expiration time set by
                       --default-reservation-expire will be used (this
                       value will be treated as a number of seconds).
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        reservations = self._driver.reserve(context, self._resources, deltas,
                                            expire=expire,
                                            project_id=project_id,
                                            user_id=user_id)

        LOG.debug(_("Created reservations %s"), reservations)

        return reservations

    def commit(self, context, reservations, project_id=None, user_id=None):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        try:
            self._driver.commit(context, reservations, project_id=project_id,
                                user_id=user_id)
        except Exception:
            # NOTE(Vek): Ignoring exceptions here is safe, because the
            # usage resynchronization and the reservation expiration
            # mechanisms will resolve the issue.  The exception is
            # logged, however, because this is less than optimal.
            LOG.exception(_("Failed to commit reservations %s"), reservations)
            return
        LOG.debug(_("Committed reservations %s"), reservations)

    def rollback(self, context, reservations, project_id=None, user_id=None):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        :param project_id: Specify the project_id if current context
                           is admin and admin wants to impact on
                           common user's tenant.
        """

        try:
            self._driver.rollback(context, reservations, project_id=project_id,
                                  user_id=user_id)
        except Exception:
            # NOTE(Vek): Ignoring exceptions here is safe, because the
            # usage resynchronization and the reservation expiration
            # mechanisms will resolve the issue.  The exception is
            # logged, however, because this is less than optimal.
            LOG.exception(_("Failed to roll back reservations %s"),
                          reservations)
            return
        LOG.debug(_("Rolled back reservations %s"), reservations)

    def usage_reset(self, context, resources):
        """
        Reset the usage records for a particular user on a list of
        resources.  This will force that user's usage records to be
        refreshed the next time a reservation is made.

        Note: this does not affect the currently outstanding
        reservations the user has; those reservations must be
        committed or rolled back (or expired).

        :param context: The request context, for access checks.
        :param resources: A list of the resource names for which the
                          usage must be reset.
        """

        self._driver.usage_reset(context, resources)

    def destroy_all_by_project_and_user(self, context, project_id, user_id):
        """
        Destroy all quotas, usages, and reservations associated with a
        project and user.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        :param user_id: The ID of the user being deleted.
        """

        self._driver.destroy_all_by_project_and_user(context,
                                                     project_id, user_id)

    def destroy_all_by_project(self, context, project_id):
        """
        Destroy all quotas, usages, and reservations associated with a
        project.

        :param context: The request context, for access checks.
        :param project_id: The ID of the project being deleted.
        """

        self._driver.destroy_all_by_project(context, project_id)

    def expire(self, context):
        """Expire reservations.

        Explores all currently existing reservations and rolls back
        any that have expired.

        :param context: The request context, for access checks.
        """

        self._driver.expire(context)

    @property
    def resources(self):
        return sorted(self._resources.keys())


QUOTAS = QuotaEngine()


resources = [
    ReservableResource('instances', '_sync_instances', 'quota_instances'),
    ReservableResource('cores', '_sync_instances', 'quota_cores'),
    ReservableResource('ram', '_sync_instances', 'quota_ram'),
    ReservableResource('security_groups', '_sync_security_groups',
                       'quota_security_groups'),
    ReservableResource('floating_ips', '_sync_floating_ips',
                       'quota_floating_ips'),
    ReservableResource('fixed_ips', '_sync_fixed_ips', 'quota_fixed_ips'),
    AbsoluteResource('metadata_items', 'quota_metadata_items'),
    AbsoluteResource('injected_files', 'quota_injected_files'),
    AbsoluteResource('injected_file_content_bytes',
                     'quota_injected_file_content_bytes'),
    AbsoluteResource('injected_file_path_bytes',
                     'quota_injected_file_path_bytes'),
    CountableResource('security_group_rules',
                      db.security_group_rule_count_by_group,
                      'quota_security_group_rules'),
    CountableResource('key_pairs', db.key_pair_count_by_user,
                      'quota_key_pairs'),
    ]


QUOTAS.register_resources(resources)
