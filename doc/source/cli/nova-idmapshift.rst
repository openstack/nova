===============
nova-idmapshift
===============

-----------------------------------------
Tool used by Nova libvirt-lxc virt driver
-----------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2012-09-27
:Copyright: OpenStack Foundation
:Version: 2012.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

nova-idmapshift [options] path

DESCRIPTION
===========

nova-idmapshift is a tool that properly sets the ownership of a filesystem for use
with linux user namespaces.  This tool can only be used with linux lxc containers.

When using user namespaces with linux lxc containers, the filesystem of the
container must be owned by the targeted user and group ids being applied
to that container. Otherwise, processes inside the container won't be able
to access the filesystem.

For example:
nova-idmapshift -i -u 0:10000:2000 -g 0:10000:2000 path

This command will idempotently shift `path` to proper ownership using
the provided uid and gid mappings.

When using the uid map string '0:10000:2000', this means that
user ids inside the container between 0 and 1999 will map to user ids on
the host between 10000 and 11999. Root (0) becomes 10000, user 1 becomes
10001, user 50 becomes 10050 and user 1999 becomes 11999. This means that
files that are owned by root need to actually be owned by user 10000, and
files owned by 50 need to be owned by 10050, and so on.

nova-idmapshift will take the uid and gid strings used for user namespaces and
properly set up the filesystem for use by those users. Uids and gids outside
of provided ranges will be mapped to nobody-id (default is max uid/gid)
so that they are inaccessible inside the container.

OPTIONS
=======

Positional arguments
~~~~~~~~~~~~~~~~~~~~

   path                 Root path of the filesystem to be shifted

Optional arguments
~~~~~~~~~~~~~~~~~~
   -h, --help           Show this help message and exit.
   -u USER_MAPS, --uid=USER_MAPS
                        User ID mappings, in the form:
                        [[guest-uid:host-uid:count],...]
   -g GROUP_MAPS, --gid=GROUP_MAPS
                        Group ID mappings, in the form:
                        [[guest-gid:host-gid:count],...]
   -n nobody-id, --nobody nobody-id
                        ID to map all unmapped uid and gids to.
                        Defaults to 65534.
   -i, --idempotent     Shift operation will only be performed if filesystem appears unshifted.
                        Defaults to false.
   -c, --confirm        Will perform check on the filesystem:

                        Returns 0 when filesystem appears shifted.

                        Returns 1 when filesystem appears unshifted.

                        Defaults to false.
   -d, --dry-run        Print chown operations, but won't perform them.
                        Defaults to false.
   -v, --verbose        Print chown operations while performing them.
                        Defaults to false.

SEE ALSO
========

* `OpenStack Nova <https://docs.openstack.org/developer/nova>`__

BUGS
====

* Nova bugs are managed at Launchpad `Bugs : Nova <https://bugs.launchpad.net/nova>`__
