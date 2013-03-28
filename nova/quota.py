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

"""Quotas for instances, volumes, and floating ips."""

import datetime

from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import cfg
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
    cfg.IntOpt('quota_volumes',
               default=10,
               help='number of volumes allowed per project'),
    cfg.IntOpt('quota_gigabytes',
               default=1000,
               help='number of volume gigabytes allowed per project'),
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

FLAGS = flags.FLAGS
FLAGS.register_opts(quota_opts)


class DbQuotaDriver(object):
    """
    Driver to perform necessary checks to enforce quotas and obtain
    quota information.  The default driver utilizes the local
    database.
    """

    def get_by_project(self, context, project_id, resource):
        """Get a specific quota by project."""

        return db.quota_get(context, project_id, resource)

    def get_by_class(self, context, quota_class, resource):
        """Get a specific quota by quota class."""

        return db.quota_class_get(context, quota_class, resource)

    def get_defaults(self, context, resources):
        """Given a list of resources, retrieve the default quotas.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        """

        quotas = {}
        for resource in resources.values():
            quotas[resource.name] = resource.default

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

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True,
                           usages=True):
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
        """

        quotas = {}
        project_quotas = db.quota_get_all_by_project(context, project_id)
        if usages:
            project_usages = db.quota_usage_get_all_by_project(context,
                                                               project_id)

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

        for resource in resources.values():
            # Omit default/quota class values
            if not defaults and resource.name not in project_quotas:
                continue

            quotas[resource.name] = dict(
                limit=project_quotas.get(resource.name, class_quotas.get(
                        resource.name, resource.default)),
                )

            # Include usages if desired.  This is optional because one
            # internal consumer of this interface wants to access the
            # usages directly from inside a transaction.
            if usages:
                usage = project_usages.get(resource.name, {})
                quotas[resource.name].update(
                    in_use=usage.get('in_use', 0),
                    reserved=usage.get('reserved', 0),
                    )

        return quotas

    def _get_quotas(self, context, resources, keys, has_sync):
        """
        A helper method which retrieves the quotas for the specific
        resources identified by keys, and which apply to the current
        context.

        :param context: The request context, for access checks.
        :param resources: A dictionary of the registered resources.
        :param keys: A list of the desired quotas to retrieve.
        :param has_sync: If True, indicates that the resource must
                         have a sync attribute; if False, indicates
                         that the resource must NOT have a sync
                         attribute.
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

        # Grab and return the quotas (without usages)
        quotas = self.get_project_quotas(context, sub_resources,
                                         context.project_id,
                                         context.quota_class, usages=False)

        return dict((k, v['limit']) for k, v in quotas.items())

    def limit_check(self, context, resources, values):
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
        """

        # Ensure no value is less than zero
        unders = [key for key, val in values.items() if val < 0]
        if unders:
            raise exception.InvalidQuotaValue(unders=sorted(unders))

        # Get the applicable quotas
        quotas = self._get_quotas(context, resources, values.keys(),
                                  has_sync=False)

        # Check the quotas and construct a list of the resources that
        # would be put over limit by the desired values
        overs = [key for key, val in values.items()
                 if quotas[key] >= 0 and quotas[key] < val]
        if overs:
            raise exception.OverQuota(overs=sorted(overs), quotas=quotas,
                                      usages={})

    def reserve(self, context, resources, deltas, expire=None):
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
        """

        # Set up the reservation expiration
        if expire is None:
            expire = FLAGS.reservation_expire
        if isinstance(expire, (int, long)):
            expire = datetime.timedelta(seconds=expire)
        if isinstance(expire, datetime.timedelta):
            expire = timeutils.utcnow() + expire
        if not isinstance(expire, datetime.datetime):
            raise exception.InvalidReservationExpiration(expire=expire)

        # Get the applicable quotas.
        # NOTE(Vek): We're not worried about races at this point.
        #            Yes, the admin may be in the process of reducing
        #            quotas, but that's a pretty rare thing.
        quotas = self._get_quotas(context, resources, deltas.keys(),
                                  has_sync=True)

        # NOTE(Vek): Most of the work here has to be done in the DB
        #            API, because we have to do it in a transaction,
        #            which means access to the session.  Since the
        #            session isn't available outside the DBAPI, we
        #            have to do the work there.
        return db.quota_reserve(context, resources, quotas, deltas, expire,
                                FLAGS.until_refresh, FLAGS.max_age)

    def commit(self, context, reservations):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        """

        db.reservation_commit(context, reservations)

    def rollback(self, context, reservations):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        """

        db.reservation_rollback(context, reservations)

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

        return FLAGS[self.flag] if self.flag else -1


class ReservableResource(BaseResource):
    """Describe a reservable resource."""

    def __init__(self, name, sync, flag=None):
        """
        Initializes a ReservableResource.

        Reservable resources are those resources which directly
        correspond to objects in the database, i.e., instances, cores,
        etc.  A ReservableResource must be constructed with a usage
        synchronization function, which will be called to determine the
        current counts of one or more resources.

        The usage synchronization function will be passed three
        arguments: an admin context, the project ID, and an opaque
        session object, which should in turn be passed to the
        underlying database function.  Synchronization functions
        should return a dictionary mapping resource names to the
        current in_use count for those resources; more than one
        resource and resource count may be returned.  Note that
        synchronization functions may be associated with more than one
        ReservableResource.

        :param name: The name of the resource, i.e., "instances".
        :param sync: A callable which returns a dictionary to
                     resynchronize the in_use count for one or more
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

        if not quota_driver_class:
            quota_driver_class = FLAGS.quota_driver

        if isinstance(quota_driver_class, basestring):
            quota_driver_class = importutils.import_object(quota_driver_class)

        self._resources = {}
        self._driver = quota_driver_class

    def __contains__(self, resource):
        return resource in self._resources

    def register_resource(self, resource):
        """Register a resource."""

        self._resources[resource.name] = resource

    def register_resources(self, resources):
        """Register a list of resources."""

        for resource in resources:
            self.register_resource(resource)

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

    def get_project_quotas(self, context, project_id, quota_class=None,
                           defaults=True, usages=True):
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
        """

        return self._driver.get_project_quotas(context, self._resources,
                                              project_id,
                                              quota_class=quota_class,
                                              defaults=defaults,
                                              usages=usages)

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

    def limit_check(self, context, **values):
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
        """

        return self._driver.limit_check(context, self._resources, values)

    def reserve(self, context, expire=None, **deltas):
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
        """

        reservations = self._driver.reserve(context, self._resources, deltas,
                                            expire=expire)

        LOG.debug(_("Created reservations %(reservations)s") % locals())

        return reservations

    def commit(self, context, reservations):
        """Commit reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        """

        try:
            self._driver.commit(context, reservations)
        except Exception:
            # NOTE(Vek): Ignoring exceptions here is safe, because the
            # usage resynchronization and the reservation expiration
            # mechanisms will resolve the issue.  The exception is
            # logged, however, because this is less than optimal.
            LOG.exception(_("Failed to commit reservations "
                            "%(reservations)s") % locals())

    def rollback(self, context, reservations):
        """Roll back reservations.

        :param context: The request context, for access checks.
        :param reservations: A list of the reservation UUIDs, as
                             returned by the reserve() method.
        """

        try:
            self._driver.rollback(context, reservations)
        except Exception:
            # NOTE(Vek): Ignoring exceptions here is safe, because the
            # usage resynchronization and the reservation expiration
            # mechanisms will resolve the issue.  The exception is
            # logged, however, because this is less than optimal.
            LOG.exception(_("Failed to roll back reservations "
                            "%(reservations)s") % locals())

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


def _sync_instances(context, project_id, session):
    return dict(zip(('instances', 'cores', 'ram'),
                    db.instance_data_get_for_project(
                context, project_id, session=session)))


def _sync_volumes(context, project_id, session):
    return dict(zip(('volumes', 'gigabytes'),
                    db.volume_data_get_for_project(
                context, project_id, session=session)))


def _sync_floating_ips(context, project_id, session):
    return dict(floating_ips=db.floating_ip_count_by_project(
            context, project_id, session=session))


def _sync_fixed_ips(context, project_id, session):
    return dict(fixed_ips=db.fixed_ip_count_by_project(
            context, project_id, session=session))


def _sync_security_groups(context, project_id, session):
    return dict(security_groups=db.security_group_count_by_project(
            context, project_id, session=session))


QUOTAS = QuotaEngine()


resources = [
    ReservableResource('instances', _sync_instances, 'quota_instances'),
    ReservableResource('cores', _sync_instances, 'quota_cores'),
    ReservableResource('ram', _sync_instances, 'quota_ram'),
    ReservableResource('volumes', _sync_volumes, 'quota_volumes'),
    ReservableResource('gigabytes', _sync_volumes, 'quota_gigabytes'),
    ReservableResource('floating_ips', _sync_floating_ips,
                       'quota_floating_ips'),
    ReservableResource('fixed_ips', _sync_fixed_ips, 'quota_fixed_ips'),
    AbsoluteResource('metadata_items', 'quota_metadata_items'),
    AbsoluteResource('injected_files', 'quota_injected_files'),
    AbsoluteResource('injected_file_content_bytes',
                     'quota_injected_file_content_bytes'),
    AbsoluteResource('injected_file_path_bytes',
                     'quota_injected_file_path_bytes'),
    ReservableResource('security_groups', _sync_security_groups,
                       'quota_security_groups'),
    CountableResource('security_group_rules',
                      db.security_group_rule_count_by_group,
                      'quota_security_group_rules'),
    CountableResource('key_pairs', db.key_pair_count_by_user,
                      'quota_key_pairs'),
    ]


QUOTAS.register_resources(resources)
