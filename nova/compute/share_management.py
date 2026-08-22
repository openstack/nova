# Copyright (c) 2024 OpenStack Foundation
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

import functools
import time

from keystoneauth1 import exceptions as keystone_exception
from openstack import exceptions as sdk_exc
from oslo_log import log as logging

from nova.compute import utils as compute_utils
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova import objects
from nova.objects import fields
from nova import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def share_synchronized(fn):
    """Serialize operations on the same share.

    Expects the wrapped method signature to be
    (self, context, instance, share_mapping, ...).
    """
    @functools.wraps(fn)
    def wrapper(self, context, instance, share_mapping, *args, **kwargs):
        @utils.synchronized(share_mapping.share_id)
        def _inner():
            return fn(self, context, instance, share_mapping,
                      *args, **kwargs)
        return _inner()
    return wrapper


class ShareManager:
    """Manages Manila share access, mounting, and lifecycle."""

    def __init__(self, manila_api, compute_driver):
        self.manila_api = manila_api
        self.driver = compute_driver

    def _set_instance_error_state(self, instance):
        try:
            instance.vm_state = vm_states.ERROR
            instance.task_state = None
            instance.save()
        except exception.InstanceNotFound:
            LOG.debug('Instance has been destroyed from under us while '
                      'trying to set it to ERROR', instance=instance)

    def get_share_info(self, context, instance, check_status=True):
        share_info = objects.ShareMappingList(context)

        for share_mapping in objects.ShareMappingList.get_by_instance_uuid(
            context, instance.uuid
        ):
            share_info.objects.append(share_mapping)

            if check_status:
                fsm = fields.ShareMappingStatus
                if (
                    share_mapping.status == fsm.ATTACHING or
                    share_mapping.status == fsm.DETACHING
                ):
                    LOG.error(
                        "Share id '%s' attached to server id '%s' is "
                        "still in '%s' state. Setting the instance "
                        "in error.",
                        share_mapping.share_id,
                        instance.uuid,
                        share_mapping.status,
                    )
                    self._set_instance_error_state(instance)
                    raise exception.ShareErrorUnexpectedStatus(
                        share_id=share_mapping.share_id,
                        instance_uuid=instance.uuid,
                    )

                if share_mapping.status == fsm.ERROR:
                    LOG.warning(
                        "Share id '%s' attached to server id '%s' is in "
                        "error state.",
                        share_mapping.share_id,
                        instance.uuid
                    )

        return share_info

    def _apply_access_policy(self, context, share_mapping):
        # Tag the lock with the owning instance so operators can trace
        # each access rule back to an instance (bug 2161761).
        lock_reason = (
            "Lock by nova for instance %s" % share_mapping.instance_uuid)
        self.manila_api.allow(
            context,
            share_mapping.share_id,
            share_mapping.access_type,
            share_mapping.access_to,
            "rw",
            lock_reason=lock_reason,
        )

    def _wait_for_access_policy(self, context, share_mapping):
        max_retries = CONF.manila.share_apply_policy_timeout
        attempt_count = 0
        while attempt_count < max_retries:
            if self.manila_api.has_access(
                context,
                share_mapping.share_id,
                share_mapping.access_type,
                share_mapping.access_to,
            ):
                LOG.debug(
                    "Allow policy set on share %s ",
                    share_mapping.share_id,
                )
                return
            LOG.debug(
                "Waiting policy to be set on share %s ",
                share_mapping.share_id,
            )
            time.sleep(1)
            attempt_count += 1

        raise exception.ShareAccessGrantError(
            share_id=share_mapping.share_id,
            reason="Failed to set allow policy on share, "
            "too many retries",
        )

    @share_synchronized
    def allow_share(self, context, instance, share_mapping):
        try:
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_ATTACH,
                phase=fields.NotificationPhase.START,
                share_id=share_mapping.share_id
            )

            self.grant_access(context, share_mapping)

            self.set_mapping_status(
                share_mapping, fields.ShareMappingStatus.INACTIVE
            )

            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_ATTACH,
                phase=fields.NotificationPhase.END,
                share_id=share_mapping.share_id
            )

        except (
            exception.ShareNotFound,
            exception.ShareProtocolNotSupported,
            exception.ShareAccessGrantError,
        ) as e:
            self.set_mapping_status(
                share_mapping, fields.ShareMappingStatus.ERROR
            )
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_ATTACH,
                phase=fields.NotificationPhase.ERROR,
                share_id=share_mapping.share_id,
                exception=e
            )
            LOG.error(e.format_message())
            raise
        except (
            sdk_exc.BadRequestException,
        ) as e:
            self.set_mapping_status(
                share_mapping, fields.ShareMappingStatus.ERROR
            )
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_ATTACH,
                phase=fields.NotificationPhase.ERROR,
                share_id=share_mapping.share_id,
                exception=e
            )
            LOG.error(
                "%s: %s error from url: %s, %s",
                e.message,
                e.source,
                e.url,
                e.details,
            )
            raise
        except keystone_exception.http.Unauthorized as e:
            self.set_mapping_status(
                share_mapping, fields.ShareMappingStatus.ERROR
            )
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_ATTACH,
                phase=fields.NotificationPhase.ERROR,
                share_id=share_mapping.share_id,
                exception=e
            )
            LOG.error(e)
            raise

    @share_synchronized
    def deny_share(self, context, instance, share_mapping):
        try:
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_DETACH,
                phase=fields.NotificationPhase.START,
                share_id=share_mapping.share_id,
            )

            # Must run before check_share_usage: populates
            # access_type/access_to needed by deny() below.
            share_mapping.set_access_according_to_protocol()

            still_used = self.check_share_usage(
                context, instance, share_mapping)

            if not still_used:
                self.manila_api.deny(
                    context,
                    share_mapping.share_id,
                    share_mapping.access_type,
                    share_mapping.access_to,
                )

            share_mapping.delete()

            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_DETACH,
                phase=fields.NotificationPhase.END,
                share_id=share_mapping.share_id,
            )

        except (
            exception.ShareAccessRemovalError,
            exception.ShareProtocolNotSupported,
        ) as e:
            self.set_mapping_status(
                share_mapping, fields.ShareMappingStatus.ERROR
            )
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_DETACH,
                phase=fields.NotificationPhase.ERROR,
                share_id=share_mapping.share_id,
                exception=e
            )
            LOG.error(e.format_message())
            raise
        except keystone_exception.http.Unauthorized as e:
            self.set_mapping_status(
                share_mapping, fields.ShareMappingStatus.ERROR
            )
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_DETACH,
                phase=fields.NotificationPhase.ERROR,
                share_id=share_mapping.share_id,
                exception=e
            )
            LOG.error(e)
            raise
        except (
            exception.ShareNotFound,
            exception.ShareAccessNotFound,
        ):
            share_mapping.delete()
            compute_utils.notify_about_share_attach_detach(
                context,
                instance,
                instance.host,
                action=fields.NotificationAction.SHARE_DETACH,
                phase=fields.NotificationPhase.END,
                share_id=share_mapping.share_id,
            )

    @staticmethod
    def _filter_mappings_to_host(context, share_mappings, host, keep_uuid):
        """Keep only the share mappings relevant to ``host``.

        NFS access is a single per-host IP rule, so only instances on
        the same host share that rule. Instances on other hosts have
        their own independent rules and must not keep this host's rule
        alive.

        ``keep_uuid`` is the instance whose access is being managed; its
        mapping is always kept (its host is not queried) so the caller
        can reason about its own mapping.
        """
        other_uuids = list({
            sm.instance_uuid for sm in share_mappings
            if sm.instance_uuid != keep_uuid})
        same_host_uuids = {keep_uuid}
        if other_uuids:
            others = objects.InstanceList.get_by_filters(
                context, {'uuid': other_uuids}, expected_attrs=[])
            same_host_uuids.update(
                inst.uuid for inst in others if inst.host == host)
        return [
            sm for sm in share_mappings
            if sm.instance_uuid in same_host_uuids
        ]

    def check_share_usage(self, context, instance, share_mapping):
        """Check if a share is still in use by active mappings.

        Returns True if the share is still needed (should not be
        revoked), False if it can be safely revoked.
        """
        instance_uuid = instance.uuid
        share_mappings_used_by_share = (
            objects.share_mapping.ShareMappingList.get_by_share_id(
                context, share_mapping.share_id
            )
        )

        # For NFS, each host has its own IP-based access rule. Only
        # consider instances on the same host when deciding whether
        # the access rule is still needed. Instances on other hosts
        # have independent access rules.
        if share_mapping.share_proto == fields.ShareMappingProto.NFS:
            share_mappings_used_by_share = self._filter_mappings_to_host(
                context, share_mappings_used_by_share, instance.host,
                instance_uuid)
        elif share_mapping.share_proto == fields.ShareMappingProto.CEPHFS:
            # CephFS uses a per-instance-per-host cephx identity, so a
            # share's access rule is never shared between instances.
            # Only this instance's own mappings decide whether the rule
            # is still needed.
            share_mappings_used_by_share = [
                sm for sm in share_mappings_used_by_share
                if sm.instance_uuid == instance_uuid
            ]
        else:
            # An unsupported protocol has no access-rule sharing model we
            # can reason about; refuse rather than guess whether the rule
            # is still needed.
            raise exception.ShareProtocolNotSupported(
                share_proto=share_mapping.share_proto)

        # The share is safe to revoke (not used) when every mapping
        # satisfies one of:
        #  - It belongs to this instance and is INACTIVE or ERROR
        #    (granted but not mounted, or broken).
        #  - It is in DETACHING state (any instance, including ours).
        # If any mapping falls outside these cases (e.g. another
        # instance is ACTIVE), the share is still in use.
        # The return value is inverted: True = still used, False = safe
        # to revoke.
        return not all(
            (
                (
                    sm.instance_uuid == instance_uuid and
                    sm.status in (
                        fields.ShareMappingStatus.INACTIVE,
                        fields.ShareMappingStatus.ERROR,
                    )
                ) or
                sm.status == fields.ShareMappingStatus.DETACHING
            )
            for sm in share_mappings_used_by_share
        )

    def mount_all(self, context, instance, share_info):
        for share_mapping in share_info:
            try:
                self.grant_access(context, share_mapping)
            except Exception:
                LOG.warning(
                    "Failed to verify Manila access for share %s, "
                    "attempting mount anyway",
                    share_mapping.share_id)
            self.mount(context, instance, share_mapping)

    def umount_all(self, context, instance, share_info):
        for share_mapping in share_info:
            self.umount(context, instance, share_mapping)

    def cleanup_shares_after_migration(
        self, context, instance, migration, reason
    ):
        """Unmount shares and revoke access on the abandoned host.

        No-op for same-host resize or when migration is None.
        """
        if migration is None:
            return
        if migration.source_compute == migration.dest_compute:
            return
        share_info = self.get_share_info(
            context, instance, check_status=False)
        self.umount_and_revoke_all(context, instance, share_info, reason)

    def umount_and_revoke_all(self, context, instance, share_info, reason):
        """Unmount shares and revoke Manila access, logging failures.

        Used during confirm/revert resize to clean up shares on
        the host being abandoned. Failures are logged but do not
        prevent the operation from continuing.
        """
        for share_mapping in share_info:
            still_mounted = False
            try:
                still_mounted = self.umount(context, instance, share_mapping)
            except Exception:
                LOG.exception(
                    "Failed to unmount share %s during %s",
                    share_mapping.share_id, reason)
            if still_mounted:
                continue
            try:
                self.revoke_access(context, share_mapping)
            except Exception:
                LOG.exception(
                    "Failed to revoke share access for %s during %s",
                    share_mapping.share_id, reason)

    @share_synchronized
    def mount(self, context, instance, share_mapping):
        try:
            share_mapping.set_access_according_to_protocol()

            if share_mapping.share_proto == (
                fields.ShareMappingProto.CEPHFS):
                share_mapping.enhance_with_ceph_credentials(context)

            LOG.debug("Mounting share %s", share_mapping.share_id)
            self.driver.mount_share(context, instance, share_mapping)

        except (
            exception.ShareNotFound,
            exception.ShareProtocolNotSupported,
            exception.ShareMountError,
        ) as e:
            LOG.error(e.format_message())
            raise
        except (sdk_exc.BadRequestException) as e:
            LOG.error("%s: %s error from url: %s, %s", e.message,
                      e.source, e.url, e.details)
            raise

    @share_synchronized
    def umount(self, context, instance, share_mapping):
        try:
            share_mapping.set_access_according_to_protocol()

            if share_mapping.share_proto == (
                fields.ShareMappingProto.CEPHFS):
                share_mapping.enhance_with_ceph_credentials(context)

            return self.driver.umount_share(context, instance, share_mapping)

        except (
            exception.ShareNotFound,
            exception.ShareUmountError,
            exception.ShareProtocolNotSupported,
        ) as e:
            LOG.error(e.format_message())
            raise

    def grant_access(self, context, share_mapping):
        """Grant Manila access for a share without side effects.

        Unlike allow_share(), this does not change ShareMapping status,
        send notifications, or modify the database. Used during migration
        where the share remains attached to the instance.

        Callers that need share-level serialization must hold the
        @utils.synchronized(share_mapping.share_id) lock.
        """
        share_mapping.set_access_according_to_protocol()

        if self.manila_api.has_access(
            context,
            share_mapping.share_id,
            share_mapping.access_type,
            share_mapping.access_to,
        ):
            LOG.debug(
                "Share %s already has access, skipping grant",
                share_mapping.share_id,
            )
            return

        self._apply_access_policy(context, share_mapping)
        self._wait_for_access_policy(context, share_mapping)

    def revoke_access(self, context, share_mapping):
        """Revoke Manila access for a share without side effects.

        Unlike deny_share(), this does not delete the ShareMapping,
        send notifications, or modify the database. Used during migration
        where the share remains attached to the instance.

        Callers that need share-level serialization must hold the lock
        themselves (e.g. deny_share uses @share_synchronized).
        """
        share_mapping.set_access_according_to_protocol()

        # NFS uses a single per-host IP access rule shared by every
        # instance on this host, so only revoke it when no other
        # instance on this host still needs it. Instances on other
        # hosts have their own independent rules. CephFS uses a
        # per-instance-per-host cephx identity, so each grant is
        # independent and always safe to revoke.
        if share_mapping.share_proto == fields.ShareMappingProto.NFS:
            share_mappings_used_by_share = self._filter_mappings_to_host(
                context,
                objects.share_mapping.ShareMappingList.get_by_share_id(
                    context, share_mapping.share_id),
                CONF.host,
                share_mapping.instance_uuid)
            # Only another instance on this host keeps the shared rule
            # alive. This instance's own mapping is being torn down, so
            # it is intentionally ignored.
            other_active = any(
                sm.instance_uuid != share_mapping.instance_uuid and
                sm.status not in (
                    fields.ShareMappingStatus.DETACHING,
                    fields.ShareMappingStatus.ERROR,
                )
                for sm in share_mappings_used_by_share
            )
            if other_active:
                LOG.debug(
                    "Share %s still used by other instances on this "
                    "host, skipping access revoke",
                    share_mapping.share_id,
                )
                return

        try:
            self.manila_api.deny(
                context,
                share_mapping.share_id,
                share_mapping.access_type,
                share_mapping.access_to,
            )
        except (
            exception.ShareNotFound,
            exception.ShareAccessNotFound,
        ):
            LOG.warning(
                "Share %s or access rule not found during revoke, "
                "ignoring", share_mapping.share_id,
            )

    def reconcile_stale_share_access(self, context):
        """Revoke Manila access rules left behind by failed cleanup."""
        if CONF.manila.auth_type is None:
            return

        # A single conductor-side query returns every share this host might
        # hold a stale rule for (instances here now, plus instances whose
        # migration touched this host). _reconcile_share revalidates each
        # share under a lock, so a rule still needed by a live instance here
        # is preserved.
        share_ids = {
            sm.share_id
            for sm in objects.ShareMappingList.get_by_host_for_reconcile(
                context, CONF.host)
        }

        if not share_ids:
            return

        try:
            for share_id in share_ids:
                try:
                    self._reconcile_share(context, share_id)
                except (
                    exception.ManilaConnectionFailed,
                    keystone_exception.MissingAuthPlugin,
                ):
                    # Manila is unreachable, or the [manila] section is not
                    # configured on this compute: re-raise so the whole pass
                    # bails out instead of the broad handler below swallowing
                    # it and retrying every remaining share against an
                    # endpoint we cannot reach.
                    raise
                except Exception:
                    LOG.exception(
                        "Failed to reconcile stale access rules for share %s",
                        share_id)
        except exception.ManilaConnectionFailed:
            LOG.warning(
                "Manila is unreachable, skipping stale share access "
                "reconcile; it will be retried on the next interval")
        except keystone_exception.MissingAuthPlugin:
            LOG.warning(
                "The [manila] section is not configured with credentials on "
                "this compute; skipping stale share access reconcile")

    def _reconcile_share(self, context, share_id):
        @utils.synchronized(share_id)
        def _locked():
            # Re-read the share's mappings and their instances from the DB
            # under the lock, so the desired access rules are computed from
            # committed ground truth at the moment we diff against manila,
            # not from a snapshot taken at the top of the pass. This closes
            # the window where a migration completing, or another host
            # attaching the share, mid-pass would make us revoke a live grant.
            mappings = objects.ShareMappingList.get_by_share_id(
                context, share_id)
            if not mappings:
                return

            instance_uuids = list({m.instance_uuid for m in mappings})
            # Not filtered by CONF.host: an instance that migrated away still
            # has a stale rule to drain here, and we need its *current* host
            # to know which per-host cephx identity is legitimate. Bounded to
            # this one share's instances (usually one), so it stays small.
            found = objects.InstanceList.get_by_filters(
                context, {'uuid': instance_uuids}, expected_attrs=[])
            instances_by_uuid = {inst.uuid: inst for inst in found}

            # Conservative: if any of the share's instances is unknown
            # (deleted or a read race) or in transit (migrating/resizing,
            # when an off-host grant legitimately still exists), skip the
            # whole share and let a later pass retry once it is quiescent.
            instances = []
            for mapping in mappings:
                instance = instances_by_uuid.get(mapping.instance_uuid)
                if instance is None or self._instance_in_transit(instance):
                    return
                instances.append(instance)

            rules = self.manila_api.get_access_rules(context, share_id)
            if mappings[0].share_proto == fields.ShareMappingProto.CEPHFS:
                self._reconcile_cephfs_rules(
                    context, share_id, mappings, instances, rules)
            else:
                self._reconcile_nfs_rules(
                    context, share_id, mappings, instances, rules)

        _locked()

    def _reconcile_cephfs_rules(
        self, context, share_id, mappings, instances, rules
    ):
        legit = {
            objects.ShareMapping._cephx_identity(
                mapping.instance_uuid, instance.host)
            for mapping, instance in zip(mappings, instances)
        }
        for rule in rules:
            # Only nova-managed per-instance identities are drained. Legacy
            # shared 'nova' grants and any non-nova cephx identity are left
            # untouched (operators drain those via the OSSN).
            if rule.access_type != 'cephx':
                continue
            if not rule.access_to.startswith('nova-'):
                continue
            if rule.access_to in legit:
                continue
            # Skip rules Manila is already processing to avoid noisy
            # repeated deny calls that generate no useful state change.
            if rule.state in ('queued_to_deny', 'denying'):
                continue
            self._revoke(context, share_id, 'cephx', rule.access_to)

    def _reconcile_nfs_rules(
        self, context, share_id, mappings, instances, rules
    ):
        # A host can only recognize its own NFS ip rule, and drains it only
        # once it no longer serves any instance on the share.
        if CONF.host in {instance.host for instance in instances}:
            return
        stale = [
            rule for rule in rules
            if rule.access_type == 'ip' and
            rule.access_to == CONF.my_shared_fs_storage_ip
        ]
        if not stale:
            return
        # Never revoke while a hard NFS mount is still present on this host:
        # dropping access under a hard mount wedges I/O in uninterruptible
        # sleep and the umount itself then hangs. Leave it for the mount
        # cleanup follow-up, which unmounts first.
        if self.driver.is_share_mounted(mappings[0]):
            LOG.warning(
                "Stale NFS access rule for share %s is still mounted on this "
                "host; skipping revoke to avoid wedging a hard mount",
                share_id)
            return
        for rule in stale:
            # Skip rules Manila is already processing to avoid noisy
            # repeated deny calls that generate no useful state change.
            if rule.state not in ('queued_to_deny', 'denying'):
                self._revoke(context, share_id, 'ip', rule.access_to)

    def _revoke(self, context, share_id, access_type, access_to):
        try:
            self.manila_api.deny(context, share_id, access_type, access_to)
            LOG.info(
                "Revoked stale Manila access rule '%s' (%s) on share %s",
                access_to, access_type, share_id)
        except (
            exception.ShareNotFound,
            exception.ShareAccessNotFound,
        ):
            # Already gone (e.g. another host raced us). Nothing to do.
            pass
        except Exception:
            LOG.exception(
                "Failed to revoke stale access rule '%s' on share %s",
                access_to, share_id)

    @staticmethod
    def _instance_in_transit(instance):
        # A migrating or resizing instance legitimately holds an access
        # rule on a host it is not currently "on" (the source grant
        # persists until confirm/revert). RESIZED covers the finished but
        # not-yet-confirmed window where task_state is already None.
        return (
            instance.task_state is not None or
            instance.vm_state == vm_states.RESIZED
        )

    @staticmethod
    def set_mapping_status(share_mapping, status):
        share_mapping.status = status
        share_mapping.save()
