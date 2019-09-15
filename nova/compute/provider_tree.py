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

"""An object describing a tree of resource providers and their inventories.

This object is not stored in the Nova API or cell databases; rather, this
object is constructed and used by the scheduler report client to track state
changes for resources on the hypervisor or baremetal node. As such, there are
no remoteable methods nor is there any interaction with the nova.db modules.
"""

import collections
import copy

import os_traits
from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_utils import uuidutils
import six

from nova.i18n import _

LOG = logging.getLogger(__name__)
_LOCK_NAME = 'provider-tree-lock'

# Point-in-time representation of a resource provider in the tree.
# Note that, whereas namedtuple enforces read-only-ness of instances as a
# whole, nothing prevents modification of the internals of attributes of
# complex types (children/inventory/traits/aggregates).  However, any such
# modifications still have no effect on the ProviderTree the instance came
# from.  Like, you can Sharpie a moustache on a Polaroid of my face, but that
# doesn't make a moustache appear on my actual face.
ProviderData = collections.namedtuple(
    'ProviderData', ['uuid', 'name', 'generation', 'parent_uuid', 'inventory',
                     'traits', 'aggregates', 'resources'])


class _Provider(object):
    """Represents a resource provider in the tree. All operations against the
    tree should be done using the ProviderTree interface, since it controls
    thread-safety.
    """
    def __init__(self, name, uuid=None, generation=None, parent_uuid=None):
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        self.uuid = uuid
        self.name = name
        self.generation = generation
        self.parent_uuid = parent_uuid
        # Contains a dict, keyed by uuid of child resource providers having
        # this provider as a parent
        self.children = {}
        # dict of inventory records, keyed by resource class
        self.inventory = {}
        # Set of trait names
        self.traits = set()
        # Set of aggregate UUIDs
        self.aggregates = set()
        # dict of resource records, keyed by resource class
        # the value is the set of objects.Resource
        self.resources = {}

    @classmethod
    def from_dict(cls, pdict):
        """Factory method producing a _Provider based on a dict with
        appropriate keys.

        :param pdict: Dictionary representing a provider, with keys 'name',
                      'uuid', 'generation', 'parent_provider_uuid'.  Of these,
                      only 'name' is mandatory.
        """
        return cls(pdict['name'], uuid=pdict.get('uuid'),
                   generation=pdict.get('generation'),
                   parent_uuid=pdict.get('parent_provider_uuid'))

    def data(self):
        inventory = copy.deepcopy(self.inventory)
        traits = copy.copy(self.traits)
        aggregates = copy.copy(self.aggregates)
        resources = copy.deepcopy(self.resources)
        return ProviderData(
            self.uuid, self.name, self.generation, self.parent_uuid,
            inventory, traits, aggregates, resources)

    def get_provider_uuids(self):
        """Returns a list, in top-down traversal order, of UUIDs of this
        provider and all its descendants.
        """
        ret = [self.uuid]
        for child in self.children.values():
            ret.extend(child.get_provider_uuids())
        return ret

    def find(self, search):
        if self.name == search or self.uuid == search:
            return self
        if search in self.children:
            return self.children[search]
        if self.children:
            for child in self.children.values():
                # We already searched for the child by UUID above, so here we
                # just check for a child name match
                if child.name == search:
                    return child
                subchild = child.find(search)
                if subchild:
                    return subchild
        return None

    def add_child(self, provider):
        self.children[provider.uuid] = provider

    def remove_child(self, provider):
        if provider.uuid in self.children:
            del self.children[provider.uuid]

    def has_inventory(self):
        """Returns whether the provider has any inventory records at all. """
        return self.inventory != {}

    def has_inventory_changed(self, new):
        """Returns whether the inventory has changed for the provider."""
        cur = self.inventory
        if set(cur) != set(new):
            return True
        for key, cur_rec in cur.items():
            new_rec = new[key]
            # If the new record contains new fields (e.g. we're adding on
            # `reserved` or `allocation_ratio`) we want to make sure to pick
            # them up
            if set(new_rec) - set(cur_rec):
                return True
            for rec_key, cur_val in cur_rec.items():
                if rec_key not in new_rec:
                    # Deliberately don't want to compare missing keys in the
                    # *new* inventory record. For instance, we will be passing
                    # in fields like allocation_ratio in the current dict but
                    # the resource tracker may only pass in the total field. We
                    # want to return that inventory didn't change when the
                    # total field values are the same even if the
                    # allocation_ratio field is missing from the new record.
                    continue
                if new_rec[rec_key] != cur_val:
                    return True
        return False

    def _update_generation(self, generation, operation):
        if generation is not None and generation != self.generation:
            msg_args = {
                'rp_uuid': self.uuid,
                'old': self.generation,
                'new': generation,
                'op': operation
            }
            LOG.debug("Updating resource provider %(rp_uuid)s generation "
                      "from %(old)s to %(new)s during operation: %(op)s",
                      msg_args)
            self.generation = generation

    def update_inventory(self, inventory, generation):
        """Update the stored inventory for the provider along with a resource
        provider generation to set the provider to. The method returns whether
        the inventory has changed.
        """
        self._update_generation(generation, 'update_inventory')
        if self.has_inventory_changed(inventory):
            LOG.debug('Updating inventory in ProviderTree for provider %s '
                      'with inventory: %s', self.uuid, inventory)
            self.inventory = copy.deepcopy(inventory)
            return True
        LOG.debug('Inventory has not changed in ProviderTree for provider: %s',
                  self.uuid)
        return False

    def have_traits_changed(self, new):
        """Returns whether the provider's traits have changed."""
        return set(new) != self.traits

    def update_traits(self, new, generation=None):
        """Update the stored traits for the provider along with a resource
        provider generation to set the provider to. The method returns whether
        the traits have changed.
        """
        self._update_generation(generation, 'update_traits')
        if self.have_traits_changed(new):
            self.traits = set(new)  # create a copy of the new traits
            return True
        return False

    def has_traits(self, traits):
        """Query whether the provider has certain traits.

        :param traits: Iterable of string trait names to look for.
        :return: True if this provider has *all* of the specified traits; False
                 if any of the specified traits are absent.  Returns True if
                 the traits parameter is empty.
        """
        return not bool(set(traits) - self.traits)

    def have_aggregates_changed(self, new):
        """Returns whether the provider's aggregates have changed."""
        return set(new) != self.aggregates

    def update_aggregates(self, new, generation=None):
        """Update the stored aggregates for the provider along with a resource
        provider generation to set the provider to. The method returns whether
        the aggregates have changed.
        """
        self._update_generation(generation, 'update_aggregates')
        if self.have_aggregates_changed(new):
            self.aggregates = set(new)  # create a copy of the new aggregates
            return True
        return False

    def in_aggregates(self, aggregates):
        """Query whether the provider is a member of certain aggregates.

        :param aggregates: Iterable of string aggregate UUIDs to look for.
        :return: True if this provider is a member of *all* of the specified
                 aggregates; False if any of the specified aggregates are
                 absent.  Returns True if the aggregates parameter is empty.
        """
        return not bool(set(aggregates) - self.aggregates)

    def have_resources_changed(self, new):
        """Returns whether the resources have changed for the provider."""
        return self.resources != new

    def update_resources(self, resources):
        """Update the stored resources for the provider. The method returns
        whether the resources have changed.
        """
        if self.have_resources_changed(resources):
            self.resources = copy.deepcopy(resources)
            return True
        return False


class ProviderTree(object):

    def __init__(self):
        """Create an empty provider tree."""
        self.lock = lockutils.internal_lock(_LOCK_NAME)
        self.roots_by_uuid = {}
        self.roots_by_name = {}

    @property
    def roots(self):
        return six.itervalues(self.roots_by_uuid)

    def get_provider_uuids(self, name_or_uuid=None):
        """Return a list, in top-down traversable order, of the UUIDs of all
        providers (in a (sub)tree).

        :param name_or_uuid: Provider name or UUID representing the root of a
                             (sub)tree for which to return UUIDs.  If not
                             specified, the method returns all UUIDs in the
                             ProviderTree.
        """
        if name_or_uuid is not None:
            with self.lock:
                return self._find_with_lock(name_or_uuid).get_provider_uuids()

        # If no name_or_uuid, get UUIDs for all providers recursively.
        ret = []
        with self.lock:
            for root in self.roots:
                ret.extend(root.get_provider_uuids())
        return ret

    def get_provider_uuids_in_tree(self, name_or_uuid):
        """Returns a list, in top-down traversable order, of the UUIDs of all
        providers in the whole tree of which the provider identified by
        ``name_or_uuid`` is a member.

        :param name_or_uuid: Provider name or UUID representing any member of
                             whole tree for which to return UUIDs.
        """
        with self.lock:
            return self._find_with_lock(
                name_or_uuid, return_root=True).get_provider_uuids()

    def populate_from_iterable(self, provider_dicts):
        """Populates this ProviderTree from an iterable of provider dicts.

        This method will ADD providers to the tree if provider_dicts contains
        providers that do not exist in the tree already and will REPLACE
        providers in the tree if provider_dicts contains providers that are
        already in the tree. This method will NOT remove providers from the
        tree that are not in provider_dicts.  But if a parent provider is in
        provider_dicts and the descendents are not, this method will remove the
        descendents from the tree.

        :param provider_dicts: An iterable of dicts of resource provider
                               information.  If a provider is present in
                               provider_dicts, all its descendants must also be
                               present.
        :raises: ValueError if any provider in provider_dicts has a parent that
                 is not in this ProviderTree or elsewhere in provider_dicts.
        """
        if not provider_dicts:
            return

        # Map of provider UUID to provider dict for the providers we're
        # *adding* via this method.
        to_add_by_uuid = {pd['uuid']: pd for pd in provider_dicts}

        with self.lock:
            # Sanity check for orphans.  Every parent UUID must either be None
            # (the provider is a root), or be in the tree already, or exist as
            # a key in to_add_by_uuid (we're adding it).
            all_parents = set([None]) | set(to_add_by_uuid)
            # NOTE(efried): Can't use get_provider_uuids directly because we're
            # already under lock.
            for root in self.roots:
                all_parents |= set(root.get_provider_uuids())
            missing_parents = set()
            for pd in to_add_by_uuid.values():
                parent_uuid = pd.get('parent_provider_uuid')
                if parent_uuid not in all_parents:
                    missing_parents.add(parent_uuid)
            if missing_parents:
                raise ValueError(
                    _("The following parents were not found: %s") %
                    ', '.join(missing_parents))

            # Ready to do the work.
            # Use to_add_by_uuid to keep track of which providers are left to
            # be added.
            while to_add_by_uuid:
                # Find a provider that's suitable to inject.
                for uuid, pd in to_add_by_uuid.items():
                    # Roots are always okay to inject (None won't be a key in
                    # to_add_by_uuid).  Otherwise, we have to make sure we
                    # already added the parent (and, by recursion, all
                    # ancestors) if present in the input.
                    parent_uuid = pd.get('parent_provider_uuid')
                    if parent_uuid not in to_add_by_uuid:
                        break
                else:
                    # This should never happen - we already ensured all parents
                    # exist in the tree, which means we can't have any branches
                    # that don't wind up at the root, which means we can't have
                    # cycles.  But to quell the paranoia...
                    raise ValueError(
                        _("Unexpectedly failed to find parents already in the "
                          "tree for any of the following: %s") %
                        ','.join(set(to_add_by_uuid)))

                # Add or replace the provider, either as a root or under its
                # parent
                try:
                    self._remove_with_lock(uuid)
                except ValueError:
                    # Wasn't there in the first place - fine.
                    pass

                provider = _Provider.from_dict(pd)
                if parent_uuid is None:
                    self.roots_by_uuid[provider.uuid] = provider
                    self.roots_by_name[provider.name] = provider
                else:
                    parent = self._find_with_lock(parent_uuid)
                    parent.add_child(provider)

                # Remove this entry to signify we're done with it.
                to_add_by_uuid.pop(uuid)

    def _remove_with_lock(self, name_or_uuid):
        found = self._find_with_lock(name_or_uuid)
        if found.parent_uuid:
            parent = self._find_with_lock(found.parent_uuid)
            parent.remove_child(found)
        else:
            del self.roots_by_uuid[found.uuid]
            del self.roots_by_name[found.name]

    def remove(self, name_or_uuid):
        """Safely removes the provider identified by the supplied name_or_uuid
        parameter and all of its children from the tree.

        :raises ValueError if name_or_uuid points to a non-existing provider.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             remove from the tree.
        """
        with self.lock:
            self._remove_with_lock(name_or_uuid)

    def new_root(self, name, uuid, generation=None):
        """Adds a new root provider to the tree, returning its UUID.

        :param name: The name of the new root provider
        :param uuid: The UUID of the new root provider
        :param generation: Generation to set for the new root provider
        :returns: the UUID of the new provider
        :raises: ValueError if a provider with the specified uuid already
                 exists in the tree.
        """

        with self.lock:
            exists = True
            try:
                self._find_with_lock(uuid)
            except ValueError:
                exists = False

            if exists:
                err = _("Provider %s already exists.")
                raise ValueError(err % uuid)

            p = _Provider(name, uuid=uuid, generation=generation)
            self.roots_by_uuid[uuid] = p
            self.roots_by_name[name] = p
            return p.uuid

    def _find_with_lock(self, name_or_uuid, return_root=False):
        # Optimization for large number of roots (e.g. ironic): if name_or_uuid
        # represents a root, this is O(1).
        found = self.roots_by_uuid.get(name_or_uuid)
        if found:
            return found
        found = self.roots_by_name.get(name_or_uuid)
        if found:
            return found

        # Okay, it's a child; do it the hard way.
        for root in self.roots:
            found = root.find(name_or_uuid)
            if found:
                return root if return_root else found
        raise ValueError(_("No such provider %s") % name_or_uuid)

    def data(self, name_or_uuid):
        """Return a point-in-time copy of the specified provider's data.

        :param name_or_uuid: Either name or UUID of the resource provider whose
                             data is to be returned.
        :return: ProviderData object representing the specified provider.
        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        """
        with self.lock:
            return self._find_with_lock(name_or_uuid).data()

    def exists(self, name_or_uuid):
        """Given either a name or a UUID, return True if the tree contains the
        provider, False otherwise.
        """
        with self.lock:
            try:
                self._find_with_lock(name_or_uuid)
                return True
            except ValueError:
                return False

    def new_child(self, name, parent, uuid=None, generation=None):
        """Creates a new child provider with the given name and uuid under the
        given parent.

        :param name: The name of the new child provider
        :param parent: Either name or UUID of the parent provider
        :param uuid: The UUID of the new child provider
        :param generation: Generation to set for the new child provider
        :returns: the UUID of the new provider

        :raises ValueError if a provider with the specified uuid or name
                already exists; or if parent_uuid points to a nonexistent
                provider.
        """
        with self.lock:
            try:
                self._find_with_lock(uuid or name)
            except ValueError:
                pass
            else:
                err = _("Provider %s already exists.")
                raise ValueError(err % (uuid or name))

            parent_node = self._find_with_lock(parent)
            p = _Provider(name, uuid, generation, parent_node.uuid)
            parent_node.add_child(p)
            return p.uuid

    def has_inventory(self, name_or_uuid):
        """Returns True if the provider identified by name_or_uuid has any
        inventory records at all.

        :raises: ValueError if a provider with uuid was not found in the tree.
        :param name_or_uuid: Either name or UUID of the resource provider
        """
        with self.lock:
            p = self._find_with_lock(name_or_uuid)
            return p.has_inventory()

    def has_inventory_changed(self, name_or_uuid, inventory):
        """Returns True if the supplied inventory is different for the provider
        with the supplied name or UUID.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             query inventory for.
        :param inventory: dict, keyed by resource class, of inventory
                          information.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.has_inventory_changed(inventory)

    def update_inventory(self, name_or_uuid, inventory, generation=None):
        """Given a name or UUID of a provider and a dict of inventory resource
        records, update the provider's inventory and set the provider's
        generation.

        :returns: True if the inventory has changed.

        :note: The provider's generation is always set to the supplied
               generation, even if there were no changes to the inventory.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             update inventory for.
        :param inventory: dict, keyed by resource class, of inventory
                          information.
        :param generation: The resource provider generation to set.  If not
                           specified, the provider's generation is not changed.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.update_inventory(inventory, generation)

    def has_sharing_provider(self, resource_class):
        """Returns whether the specified provider_tree contains any sharing
        providers of inventory of the specified resource_class.
        """
        for rp_uuid in self.get_provider_uuids():
            pdata = self.data(rp_uuid)
            has_rc = resource_class in pdata.inventory
            is_sharing = os_traits.MISC_SHARES_VIA_AGGREGATE in pdata.traits
            if has_rc and is_sharing:
                return True
        return False

    def has_traits(self, name_or_uuid, traits):
        """Given a name or UUID of a provider, query whether that provider has
        *all* of the specified traits.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             query for traits.
        :param traits: Iterable of string trait names to search for.
        :return: True if this provider has *all* of the specified traits; False
                 if any of the specified traits are absent.  Returns True if
                 the traits parameter is empty, even if the provider has no
                 traits.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.has_traits(traits)

    def have_traits_changed(self, name_or_uuid, traits):
        """Returns True if the specified traits list is different for the
        provider with the specified name or UUID.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             query traits for.
        :param traits: Iterable of string trait names to compare against the
                       provider's traits.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.have_traits_changed(traits)

    def update_traits(self, name_or_uuid, traits, generation=None):
        """Given a name or UUID of a provider and an iterable of string trait
        names, update the provider's traits and set the provider's generation.

        :returns: True if the traits list has changed.

        :note: The provider's generation is always set to the supplied
               generation, even if there were no changes to the traits.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             update traits for.
        :param traits: Iterable of string trait names to set.
        :param generation: The resource provider generation to set.  If None,
                           the provider's generation is not changed.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.update_traits(traits, generation=generation)

    def add_traits(self, name_or_uuid, *traits):
        """Set traits on a provider, without affecting existing traits.

        :param name_or_uuid: The name or UUID of the provider whose traits are
                             to be affected.
        :param traits: String names of traits to be added.
        """
        if not traits:
            return
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            final_traits = provider.traits | set(traits)
            provider.update_traits(final_traits)

    def remove_traits(self, name_or_uuid, *traits):
        """Unset traits on a provider, without affecting other existing traits.

        :param name_or_uuid: The name or UUID of the provider whose traits are
                             to be affected.
        :param traits: String names of traits to be removed.
        """
        if not traits:
            return
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            final_traits = provider.traits - set(traits)
            provider.update_traits(final_traits)

    def in_aggregates(self, name_or_uuid, aggregates):
        """Given a name or UUID of a provider, query whether that provider is a
        member of *all* the specified aggregates.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             query for aggregates.
        :param aggregates: Iterable of string aggregate UUIDs to search for.
        :return: True if this provider is associated with *all* of the
                 specified aggregates; False if any of the specified aggregates
                 are absent.  Returns True if the aggregates parameter is
                 empty, even if the provider has no aggregate associations.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.in_aggregates(aggregates)

    def have_aggregates_changed(self, name_or_uuid, aggregates):
        """Returns True if the specified aggregates list is different for the
        provider with the specified name or UUID.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             query aggregates for.
        :param aggregates: Iterable of string aggregate UUIDs to compare
                           against the provider's aggregates.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.have_aggregates_changed(aggregates)

    def update_aggregates(self, name_or_uuid, aggregates, generation=None):
        """Given a name or UUID of a provider and an iterable of string
        aggregate UUIDs, update the provider's aggregates and set the
        provider's generation.

        :returns: True if the aggregates list has changed.

        :note: The provider's generation is always set to the supplied
               generation, even if there were no changes to the aggregates.

        :raises: ValueError if a provider with name_or_uuid was not found in
                 the tree.
        :param name_or_uuid: Either name or UUID of the resource provider to
                             update aggregates for.
        :param aggregates: Iterable of string aggregate UUIDs to set.
        :param generation: The resource provider generation to set.  If None,
                           the provider's generation is not changed.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.update_aggregates(aggregates,
                                              generation=generation)

    def add_aggregates(self, name_or_uuid, *aggregates):
        """Set aggregates on a provider, without affecting existing aggregates.

        :param name_or_uuid: The name or UUID of the provider whose aggregates
                             are to be affected.
        :param aggregates: String UUIDs of aggregates to be added.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            final_aggs = provider.aggregates | set(aggregates)
            provider.update_aggregates(final_aggs)

    def remove_aggregates(self, name_or_uuid, *aggregates):
        """Unset aggregates on a provider, without affecting other existing
        aggregates.

        :param name_or_uuid: The name or UUID of the provider whose aggregates
                             are to be affected.
        :param aggregates: String UUIDs of aggregates to be removed.
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            final_aggs = provider.aggregates - set(aggregates)
            provider.update_aggregates(final_aggs)

    def update_resources(self, name_or_uuid, resources):
        """Given a name or UUID of a provider and a dict of resources,
        update the provider's resources.

        :param name_or_uuid: The name or UUID of the provider whose resources
                             are to be affected.
        :param resources: A dict keyed by resource class, and the value is a
                          set of objects.Resource instance.
        :returns: True if the resources are updated else False
        """
        with self.lock:
            provider = self._find_with_lock(name_or_uuid)
            return provider.update_resources(resources)
