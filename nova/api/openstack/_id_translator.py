from nova import datastore


class RackspaceAPIIdTranslator(object):
    """
    Converts Rackspace API ids to and from the id format for a given
    strategy.
    """

    def __init__(self, id_type, service_name):
        """
        Creates a translator for ids of the given type (e.g. 'flavor'), for the
        given storage service backend class name (e.g. 'LocalFlavorService').
        """

        self._store = datastore.Redis.instance()
        key_prefix = "rsapi.idtranslator.%s.%s" % (id_type, service_name)
        # Forward (strategy format -> RS format) and reverse translation keys
        self._fwd_key = "%s.fwd" % key_prefix
        self._rev_key = "%s.rev" % key_prefix

    def to_rs_id(self, opaque_id):
        """Convert an id from a strategy-specific one to a Rackspace one."""
        result = self._store.hget(self._fwd_key, str(opaque_id))
        if result:  # we have a mapping from opaque to RS for this strategy
            return int(result)
        else:
            # Store the mapping.
            nextid = self._store.incr("%s.lastid" % self._fwd_key)
            if self._store.hsetnx(self._fwd_key, str(opaque_id), nextid):
                # If someone else didn't beat us to it, store the reverse
                # mapping as well.
                self._store.hset(self._rev_key, nextid, str(opaque_id))
                return nextid
            else:
                # Someone beat us to it; use their number instead, and
                # discard nextid (which is OK -- we don't require that
                # every int id be used.)
                return int(self._store.hget(self._fwd_key, str(opaque_id)))

    def from_rs_id(self, rs_id):
        """Convert a Rackspace id to a strategy-specific one."""
        return self._store.hget(self._rev_key, rs_id)
