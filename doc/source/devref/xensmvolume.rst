Xen Storage Manager Volume Driver
=================================

The Xen Storage Manager (xensm) driver for Nova-Volume is based on XenAPI Storage Manager. This will not only provide basic storage functionality (like volume creation, and destruction) on a number of different storage back-ends, such as Netapp, NFS, etc. but it will also enable the capability of using more sophisticated storage back-ends for operations like cloning/snapshotting etc. To have an idea of the benefits of using XenAPI SM to provide back-end storage services, the list below shows some of the storage plugins already supported in XenServer/XCP:

-   NFS VHD: SR plugin which stores disks as VHD files on a remote NFS filesystem
-   Local VHD on LVM: SR plugin which represents disks as VHD disks on Logical Volumes within a locally-attached Volume Group
-   HBA LUN-per-VDI driver: SR plugin which represents LUNs as VDIs sourced by hardware HBA adapters, e.g. hardware-based iSCSI or FC support
-   NetApp: SR driver for mapping of LUNs to VDIs on a NETAPP server, providing use of fast snapshot and clone features on the filer
-   LVHD over FC: SR plugin which represents disks as VHDs on Logical Volumes within a Volume Group created on an HBA LUN, e.g. hardware-based iSCSI or FC support
-   iSCSI: Base ISCSI SR driver, provides a LUN-per-VDI. Does not support creation of VDIs but accesses existing LUNs on a target.
-   LVHD over iSCSI: SR plugin which represents disks as Logical Volumes within a Volume Group created on an iSCSI LUN
-   EqualLogic: SR driver for mapping of LUNs to VDIs on an EQUALLOGIC array group, providing use of fast snapshot and clone features on the array 

Glossary
=========

    XenServer: Commercial, supported product from Citrix

    Xen Cloud Platform (XCP): Open-source equivalent of XenServer (and the development project for the toolstack). Everything said about XenServer below applies equally to XCP

    XenAPI: The management API exposed by XenServer and XCP

    xapi: The primary daemon on XenServer and Xen Cloud Platform; the one that exposes the XenAPI 


Design
=======

Definitions
-----------

Backend: A term for a particular storage backend. This could be iSCSI, NFS, Netapp etc.
Backend-config: All the parameters required to connect to a specific backend. For e.g. For NFS, this would be the server, path, etc.
Flavor: This term is equivalent to volume "types". A user friendly term to specify some notion of quality of service. For example, "gold" might mean that the volumes will use a backend where backups are possible.

A flavor can be associated with multiple backends. The volume scheduler, with the help of the driver, will decide which backend will be used to create a volume of a particular flavor. Currently, the driver uses a simple "first-fit" policy, where the first backend that can successfully create this volume is the one that is used.

Operation
----------

Using the nova-manage command detailed in the implementation, an admin can add flavors and backends.

One or more nova-volume service instances will be deployed per availability zone. When an instance is started, it will create storage repositories (SRs) to connect to the backends available within that zone. All nova-volume instances within a zone can see all the available backends. These instances are completely symmetric and hence should be able to service any create_volume request within the zone.


Commands
=========

A category called "sm" has been added to nova-manage in the class StorageManagerCommands.

The following actions will be added:

-    flavor_list
-    flavor_create
-    flavor_delete
-    backend_list
-    backend_add
-    backend_remove 

Usage:
------

nova-manage sm flavor_create <label> <description>

nova-manage sm flavor_delete<label>

nova-manage sm backend_add <flavor label> <SR type> [config connection parameters]

Note: SR type and config connection parameters are in keeping with the Xen Command Line Interface. http://support.citrix.com/article/CTX124887

nova-manage sm backend_delete <backend-id>

Examples:
---------

nova-manage sm flavor_create gold "Not all that glitters"

nova-manage sm flavor_delete gold

nova-manage sm backend_add gold nfs name_label=toybox-renuka server=myserver serverpath=/local/scratch/myname

nova-manage sm backend_remove 1

API Changes
===========

No API changes have been introduced so far. The existing euca-create-volume and euca-delete-volume commands (or equivalent OpenStack API commands) should be used.
