# Copyright 2016 IBM Corp.
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
CLI interface for nova status commands.
"""

from __future__ import print_function

import collections
import functools
import sys
import traceback

from keystoneauth1 import exceptions as ks_exc
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_upgradecheck import upgradecheck
import pkg_resources
import six
from sqlalchemy import func as sqlfunc
from sqlalchemy import MetaData, Table, and_, select

from nova.cmd import common as cmd_common
import nova.conf
from nova import config
from nova import context as nova_context
from nova.db.sqlalchemy import api as db_session
from nova import exception
from nova.i18n import _
from nova.objects import cell_mapping as cell_mapping_obj
from nova import policy
from nova import utils
from nova import version
from nova.volume import cinder

CONF = nova.conf.CONF

# NOTE(efried): 1.35 is required by nova-scheduler to support the root_required
# queryparam to make GET /allocation_candidates require that a trait be present
# on the root provider, irrespective of how the request groups are specified.
# NOTE: If you bump this version, remember to update the history
# section in the nova-status man page (doc/source/cli/nova-status).
MIN_PLACEMENT_MICROVERSION = "1.35"

# NOTE(mriedem): 3.44 is needed to work with volume attachment records which
# are required for supporting multi-attach capable volumes.
MIN_CINDER_MICROVERSION = '3.44'


class UpgradeCommands(upgradecheck.UpgradeCommands):
    """Commands related to upgrades.

    The subcommands here must not rely on the nova object model since they
    should be able to run on n-1 data. Any queries to the database should be
    done through the sqlalchemy query language directly like the database
    schema migrations.
    """

    def _count_compute_nodes(self, context=None):
        """Returns the number of compute nodes in the cell database."""
        # NOTE(mriedem): This does not filter based on the service status
        # because a disabled nova-compute service could still be reporting
        # inventory info to the placement service. There could be an outside
        # chance that there are compute node records in the database for
        # disabled nova-compute services that aren't yet upgraded to Ocata or
        # the nova-compute service was deleted and the service isn't actually
        # running on the compute host but the operator hasn't cleaned up the
        # compute_nodes entry in the database yet. We consider those edge cases
        # here and the worst case scenario is we give a warning that there are
        # more compute nodes than resource providers. We can tighten this up
        # later if needed, for example by not including compute nodes that
        # don't have a corresponding nova-compute service in the services
        # table, or by only counting compute nodes with a service version of at
        # least 15 which was the highest service version when Newton was
        # released.
        meta = MetaData(bind=db_session.get_engine(context=context))
        compute_nodes = Table('compute_nodes', meta, autoload=True)
        return select([sqlfunc.count()]).select_from(compute_nodes).where(
                compute_nodes.c.deleted == 0).scalar()

    def _check_cellsv2(self):
        """Checks to see if cells v2 has been setup.

        These are the same checks performed in the 030_require_cell_setup API
        DB migration except we expect this to be run AFTER the
        nova-manage cell_v2 simple_cell_setup command, which would create the
        cell and host mappings and sync the cell0 database schema, so we don't
        check for flavors at all because you could create those after doing
        this on an initial install. This also has to be careful about checking
        for compute nodes if there are no host mappings on a fresh install.
        """
        meta = MetaData()
        meta.bind = db_session.get_api_engine()

        cell_mappings = self._get_cell_mappings()
        count = len(cell_mappings)
        # Two mappings are required at a minimum, cell0 and your first cell
        if count < 2:
            msg = _('There needs to be at least two cell mappings, one for '
                    'cell0 and one for your first cell. Run command '
                    '\'nova-manage cell_v2 simple_cell_setup\' and then '
                    'retry.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        cell0 = any(mapping.is_cell0() for mapping in cell_mappings)
        if not cell0:
            msg = _('No cell0 mapping found. Run command '
                    '\'nova-manage cell_v2 simple_cell_setup\' and then '
                    'retry.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        host_mappings = Table('host_mappings', meta, autoload=True)
        count = select([sqlfunc.count()]).select_from(host_mappings).scalar()
        if count == 0:
            # This may be a fresh install in which case there may not be any
            # compute_nodes in the cell database if the nova-compute service
            # hasn't started yet to create those records. So let's query the
            # cell database for compute_nodes records and if we find at least
            # one it's a failure.
            num_computes = self._count_compute_nodes()
            if num_computes > 0:
                msg = _('No host mappings found but there are compute nodes. '
                        'Run command \'nova-manage cell_v2 '
                        'simple_cell_setup\' and then retry.')
                return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

            msg = _('No host mappings or compute nodes were found. Remember '
                    'to run command \'nova-manage cell_v2 discover_hosts\' '
                    'when new compute hosts are deployed.')
            return upgradecheck.Result(upgradecheck.Code.SUCCESS, msg)

        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    @staticmethod
    def _placement_get(path):
        """Do an HTTP get call against placement engine.

        This is in a dedicated method to make it easier for unit
        testing purposes.

        """
        client = utils.get_ksa_adapter('placement')
        return client.get(path, raise_exc=True).json()

    def _check_placement(self):
        """Checks to see if the placement API is ready for scheduling.

        Checks to see that the placement API service is registered in the
        service catalog and that we can make requests against it.
        """
        try:
            # TODO(efried): Use ksa's version filtering in _placement_get
            versions = self._placement_get("/")
            max_version = pkg_resources.parse_version(
                versions["versions"][0]["max_version"])
            needs_version = pkg_resources.parse_version(
                MIN_PLACEMENT_MICROVERSION)
            if max_version < needs_version:
                msg = (_('Placement API version %(needed)s needed, '
                         'you have %(current)s.') %
                       {'needed': needs_version, 'current': max_version})
                return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.MissingAuthPlugin:
            msg = _('No credentials specified for placement API in nova.conf.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.Unauthorized:
            msg = _('Placement service credentials do not work.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.EndpointNotFound:
            msg = _('Placement API endpoint not found.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.DiscoveryFailure:
            msg = _('Discovery for placement API URI failed.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.NotFound:
            msg = _('Placement API does not seem to be running.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    @staticmethod
    def _get_non_cell0_mappings():
        """Queries the API database for non-cell0 cell mappings.

        :returns: list of nova.objects.CellMapping objects
        """
        return UpgradeCommands._get_cell_mappings(include_cell0=False)

    @staticmethod
    def _get_cell_mappings(include_cell0=True):
        """Queries the API database for cell mappings.

        .. note:: This method is unique in that it queries the database using
                  CellMappingList.get_all() rather than a direct query using
                  the sqlalchemy models. This is because
                  CellMapping.database_connection can be a template and the
                  object takes care of formatting the URL. We cannot use
                  RowProxy objects from sqlalchemy because we cannot set the
                  formatted 'database_connection' value back on those objects
                  (they are read-only).

        :param include_cell0: True if cell0 should be returned, False if cell0
            should be excluded from the results.
        :returns: list of nova.objects.CellMapping objects
        """
        ctxt = nova_context.get_admin_context()
        cell_mappings = cell_mapping_obj.CellMappingList.get_all(ctxt)
        if not include_cell0:
            # Since CellMappingList does not implement remove() we have to
            # create a new list and exclude cell0.
            mappings = [mapping for mapping in cell_mappings
                        if not mapping.is_cell0()]
            cell_mappings = cell_mapping_obj.CellMappingList(objects=mappings)
        return cell_mappings

    @staticmethod
    def _is_ironic_instance_migrated(extras, inst):
        extra = (extras.select().where(extras.c.instance_uuid == inst['uuid']
                                       ).execute().first())
        # Pull the flavor and deserialize it. Note that the flavor info for an
        # instance is a dict keyed by "cur", "old", "new" and we want the
        # current flavor.
        flavor = jsonutils.loads(extra['flavor'])['cur']['nova_object.data']
        # Do we have a custom resource flavor extra spec?
        specs = flavor['extra_specs'] if 'extra_specs' in flavor else {}
        for spec_key in specs:
            if spec_key.startswith('resources:CUSTOM_'):
                # We found a match so this instance is good.
                return True
        return False

    def _check_ironic_flavor_migration(self):
        """In Pike, ironic instances and flavors need to be migrated to use
        custom resource classes. In ironic, the node.resource_class should be
        set to some custom resource class value which should match a
        "resources:<custom resource class name>" flavor extra spec on baremetal
        flavors. Existing ironic instances will have their embedded
        instance.flavor.extra_specs migrated to use the matching ironic
        node.resource_class value in the nova-compute service, or they can
        be forcefully migrated using "nova-manage db ironic_flavor_migration".

        In this check, we look for all ironic compute nodes in all non-cell0
        cells, and from those ironic compute nodes, we look for an instance
        that has a "resources:CUSTOM_*" key in it's embedded flavor extra
        specs.
        """
        cell_mappings = self._get_non_cell0_mappings()
        ctxt = nova_context.get_admin_context()
        # dict of cell identifier (name or uuid) to number of unmigrated
        # instances
        unmigrated_instance_count_by_cell = collections.defaultdict(int)
        for cell_mapping in cell_mappings:
            with nova_context.target_cell(ctxt, cell_mapping) as cctxt:
                # Get the (non-deleted) ironic compute nodes in this cell.
                meta = MetaData(bind=db_session.get_engine(context=cctxt))
                compute_nodes = Table('compute_nodes', meta, autoload=True)
                ironic_nodes = (
                    compute_nodes.select().where(and_(
                        compute_nodes.c.hypervisor_type == 'ironic',
                        compute_nodes.c.deleted == 0
                    )).execute().fetchall())

                if ironic_nodes:
                    # We have ironic nodes in this cell, let's iterate over
                    # them looking for instances.
                    instances = Table('instances', meta, autoload=True)
                    extras = Table('instance_extra', meta, autoload=True)
                    for node in ironic_nodes:
                        nodename = node['hypervisor_hostname']
                        # Get any (non-deleted) instances for this node.
                        ironic_instances = (
                            instances.select().where(and_(
                                instances.c.node == nodename,
                                instances.c.deleted == 0
                            )).execute().fetchall())
                        # Get the instance_extras for each instance so we can
                        # find the flavors.
                        for inst in ironic_instances:
                            if not self._is_ironic_instance_migrated(
                                    extras, inst):
                                # We didn't find the extra spec key for this
                                # instance so increment the number of
                                # unmigrated instances in this cell.
                                unmigrated_instance_count_by_cell[
                                    cell_mapping.uuid] += 1

        if not cell_mappings:
            # There are no non-cell0 mappings so we can't determine this, just
            # return a warning. The cellsv2 check would have already failed
            # on this.
            msg = (_('Unable to determine ironic flavor migration without '
                     'cell mappings.'))
            return upgradecheck.Result(upgradecheck.Code.WARNING, msg)

        if unmigrated_instance_count_by_cell:
            # There are unmigrated ironic instances, so we need to fail.
            msg = (_('There are (cell=x) number of unmigrated instances in '
                     'each cell: %s. Run \'nova-manage db '
                     'ironic_flavor_migration\' on each cell.') %
                   ' '.join('(%s=%s)' % (
                       cell_id, unmigrated_instance_count_by_cell[cell_id])
                            for cell_id in
                            sorted(unmigrated_instance_count_by_cell.keys())))
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        # Either there were no ironic compute nodes or all instances for
        # those nodes are already migrated, so there is nothing to do.
        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_cinder(self):
        """Checks to see that the cinder API is available at a given minimum
        microversion.
        """
        # Check to see if nova is even configured for Cinder yet (fresh install
        # or maybe not using Cinder at all).
        if CONF.cinder.auth_type is None:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)

        try:
            # TODO(mriedem): Eventually use get_ksa_adapter here when it
            # supports cinder.
            cinder.is_microversion_supported(
                nova_context.get_admin_context(), MIN_CINDER_MICROVERSION)
        except exception.CinderAPIVersionNotAvailable:
            return upgradecheck.Result(
                upgradecheck.Code.FAILURE,
                _('Cinder API %s or greater is required. Deploy at least '
                  'Cinder 12.0.0 (Queens).') % MIN_CINDER_MICROVERSION)
        except Exception as ex:
            # Anything else trying to connect, like bad config, is out of our
            # hands so just return a warning.
            return upgradecheck.Result(
                upgradecheck.Code.WARNING,
                _('Unable to determine Cinder API version due to error: %s') %
                six.text_type(ex))
        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_policy(self):
        """Checks to see if policy file is overwritten with the new
        defaults.
        """
        msg = _("Your policy file contains rules which examine token scope, "
                "which may be due to generation with the new defaults. "
                "If that is done intentionally to migrate to the new rule "
                "format, then you are required to enable the flag "
                "'oslo_policy.enforce_scope=True' and educate end users on "
                "how to request scoped tokens from Keystone. Another easy "
                "and recommended way for you to achieve the same is via two "
                "flags, 'oslo_policy.enforce_scope=True' and "
                "'oslo_policy.enforce_new_defaults=True' and avoid "
                "overwriting the file. Please refer to this document to "
                "know the complete migration steps: "
                "https://docs.openstack.org/nova/latest/configuration"
                "/policy-concepts.html. If you did not intend to migrate "
                "to new defaults in this upgrade, then with your current "
                "policy file the scope checking rule will fail. A possible "
                "reason for such a policy file is that you generated it with "
                "'oslopolicy-sample-generator' in json format. "
                "Three ways to fix this until you are ready to migrate to "
                "scoped policies: 1. Generate the policy file with "
                "'oslopolicy-sample-generator' in yaml format, keep "
                "the generated content commented out, and update "
                "the generated policy.yaml location in "
                "``oslo_policy.policy_file``. "
                "2. Use a pre-existing sample config file from the Train "
                "release. 3. Use an empty or non-existent file to take all "
                "the defaults.")
        rule = "system_admin_api"
        rule_new_default = "role:admin and system_scope:all"
        status = upgradecheck.Result(upgradecheck.Code.SUCCESS)
        # NOTE(gmann): Initialise the policy if it not initialized.
        # We need policy enforcer with all the rules loaded to check
        # their value with defaults.
        try:
            if policy._ENFORCER is None:
                policy.init(suppress_deprecation_warnings=True)

            # For safer side, recheck that the enforcer is available before
            # upgrade checks. If something is wrong on oslo side and enforcer
            # is still not available the return warning to avoid any false
            # result.
            if policy._ENFORCER is not None:
                current_rule = str(policy._ENFORCER.rules[rule]).strip("()")
                if (current_rule == rule_new_default and
                    not CONF.oslo_policy.enforce_scope):
                    status = upgradecheck.Result(upgradecheck.Code.WARNING,
                                                 msg)
            else:
                status = upgradecheck.Result(
                    upgradecheck.Code.WARNING,
                    _('Policy is not initialized to check the policy rules'))
        except Exception as ex:
            status = upgradecheck.Result(
                upgradecheck.Code.WARNING,
                _('Unable to perform policy checks due to error: %s') %
                six.text_type(ex))
        # reset the policy state so that it can be initialized from fresh if
        # operator changes policy file after running this upgrade checks.
        policy.reset()
        return status

    # The format of the check functions is to return an upgradecheck.Result
    # object with the appropriate upgradecheck.Code and details set. If the
    # check hits warnings or failures then those should be stored in the
    # returned upgradecheck.Result's "details" attribute. The summary will
    # be rolled up at the end of the check() function. These functions are
    # intended to be run in order and build on top of each other so order
    # matters.
    _upgrade_checks = (
        # Added in Ocata
        (_('Cells v2'), _check_cellsv2),
        # Added in Ocata
        (_('Placement API'), _check_placement),
        # Added in Rocky (but also useful going back to Pike)
        (_('Ironic Flavor Migration'), _check_ironic_flavor_migration),
        # Added in Train
        (_('Cinder API'), _check_cinder),
        # Added in Ussuri
        (_('Policy Scope-based Defaults'), _check_policy),
    )


CATEGORIES = {
    'upgrade': UpgradeCommands,
}


add_command_parsers = functools.partial(cmd_common.add_command_parsers,
                                        categories=CATEGORIES)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 help='Available categories',
                                 handler=add_command_parsers)


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opt(category_opt)
    config.parse_args(sys.argv)

    if CONF.category.name == "version":
        print(version.version_string_with_package())
        return 0

    if CONF.category.name == "bash-completion":
        cmd_common.print_bash_completion(CATEGORIES)
        return 0

    try:
        fn, fn_args, fn_kwargs = cmd_common.get_action_fn()
        ret = fn(*fn_args, **fn_kwargs)
        return ret
    except Exception:
        print(_('Error:\n%s') % traceback.format_exc())
        # This is 255 so it's not confused with the upgrade check exit codes.
        return 255
