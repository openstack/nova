     --^--
    /^ ^ ^\
       | O R B I T
       |
     | | http://www.orbitproject.eu/
      U

### Introduction

This repository includes a set of patches that aims to introduce high
availability in OpenStack Nova by implementing an integration with a
fault tolerance feature in QEMU called
[COLO (COarse Grain LOck Stepping)](http://wiki.qemu.org/Features/COLO).

Both the name COLO and fault tolerance (FT) is used to refer to the same high
availability mechanism. While COLO is the actual technique used,
fault tolerance could be seen as a higher layer of abstraction in OpenStack
dealing with redundant instances without being aware about the actual
implementation down the stack.

### Prerequisites
COLO is currently not supported upstream, however, you can get patches for
both [QEMU](https://github.com/orbitfp7/qemu/tree/orbit-wp4-colo-mar16) and
[libvirt](https://github.com/orbitfp7/libvirt/tree/colo-postcopy). These should
be setup and installed before you try to use the OpenStack patches.
QEMU should be installed using QEMU's normal installation process, adding `--enable-colo --enable-qourum` during the configure stage.

These patches are based on the Juno version of Nova. Make sure that your
OpenStack setup is running or is compatible with Nova running Juno.

### Installation
To be able to use COLO through OpenStack you need to install the COLO patches.
If you are feeling brave, you could try to apply the patches yourself,
otherwise, replace your current Nova source code by cloning this repository.

There is also a few minor patches for the
[python-novaclient](https://github.com/orbitfp7/python-novaclient/blob/fault-tolerance/README_FT.rst)
and [Horizon](https://github.com/orbitfp7/horizon/blob/fault-tolerance/README_FT.rst)
integrating COLO/FT. See the links for their specific installation instructions.

### Setting up

There are a few different configurations that are required to setup the COLO
implementation properly. Edit your `nova.conf` with the following changes:

```
[DEFAULT]
# Change to the FT scheduler which schedules a list of pairs or sets of
# hosts rather than a list of single hosts
scheduler_driver = nova.scheduler.fault_tolerance_scheduler.FaultToleranceScheduler
```
```
# Disable VNC (more specifically -nographics in QEMU). This currently creates
# some mismatching of the PCI addresses in the primary and secondary guest
vnc_enabled = false
```
```
# Disable force config drive since it's not working with live migrations
# Disable it by removing force_config_drive = always
```
```
[libvirt]
# *Optional* Change path of the block replication drives
# For example if you want to use a RAM-based filesystem
block_replication_path=/path
```

If you're modifying and running an OpenStack installation. Restart all
of the nova components when the FT patches and configuration has been added.

### Usage

Enabling COLO in a new instance is done by modifying the flavor extra specs

Example using the python-novaclient

`nova flavor-key 1 set ft:enabled=1`

To recover when a failure has happened you can either use the API or the
nova client with the
[COLO patches](https://github.com/orbitfp7/python-novaclient/tree/fault-tolerance/)

**API**

```
POST http://[nova-api host]:8774/v2/[project ID]/servers/[instance ID]/action

#Header
Content-Type: application/json
X-Auth-Token: [token]

#Payload
{ "failover": null }
```

**Nova client**

`nova failover [instance name/ID]`

### Disclaimers

Quorums are at the time of writing not supported in libvirt. Since COLO depends
on the quorum functionality in QEMU this is handled a bit differently from
the rest of the modifications. Quorum is added to the disk command line through
libvirt's QEMU commandline XML rather than using the usual disk XML.

These patches are not reviewed and accepted by the OpenStack community.

