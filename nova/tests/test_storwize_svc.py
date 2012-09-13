# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 IBM, Inc.
# Copyright (c) 2012 OpenStack LLC.
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
#
# Authors:
#   Ronen Kat <ronenkat@il.ibm.com>
#   Avishay Traeger <avishay@il.ibm.com>

"""
Tests for the IBM Storwize V7000 and SVC volume driver.
"""

import random
import socket

from nova import exception
from nova import flags
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova import test
from nova.volume import storwize_svc

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


class StorwizeSVCManagementSimulator:
    def __init__(self, pool_name):
        self._flags = {"storwize_svc_volpool_name": pool_name}
        self._volumes_list = {}
        self._hosts_list = {}
        self._mappings_list = {}
        self._fcmappings_list = {}
        self._next_cmd_error = {
            "lsportip": "",
            "lsnodecanister": "",
            "mkvdisk": "",
            "lsvdisk": "",
            "lsfcmap": "",
            "prestartfcmap": "",
            "startfcmap": "",
            "rmfcmap": "",
        }
        self._errors = {
            "CMMVC5701E": ("", "CMMVC5701E No object ID was specified."),
            "CMMVC6035E": ("", "CMMVC6035E The action failed as the " +
                               "object already exists."),
            "CMMVC5753E": ("", "CMMVC5753E The specified object does not " +
                               "exist or is not a suitable candidate."),
            "CMMVC5707E": ("", "CMMVC5707E Required parameters are missing."),
            "CMMVC6581E": ("", "CMMVC6581E The command has failed because " +
                               "the maximum number of allowed iSCSI " +
                               "qualified names (IQNs) has been reached, " +
                               "or the IQN is already assigned or is not " +
                               "valid."),
            "CMMVC5754E": ("", "CMMVC5754E The specified object does not " +
                               "exist, or the name supplied does not meet " +
                               "the naming rules."),
            "CMMVC6071E": ("", "CMMVC6071E The VDisk-to-host mapping was " +
                               "not created because the VDisk is already " +
                               "mapped to a host."),
            "CMMVC5879E": ("", "CMMVC5879E The VDisk-to-host mapping was " +
                               "not created because a VDisk is already " +
                               "mapped to this host with this SCSI LUN."),
            "CMMVC5840E": ("", "CMMVC5840E The virtual disk (VDisk) was " +
                               "not deleted because it is mapped to a " +
                               "host or because it is part of a FlashCopy " +
                               "or Remote Copy mapping, or is involved in " +
                               "an image mode migrate."),
            "CMMVC6527E": ("", "CMMVC6527E The name that you have entered " +
                               "is not valid. The name can contain letters, " +
                               "numbers, spaces, periods, dashes, and " +
                               "underscores. The name must begin with a " +
                               "letter or an underscore. The name must not " +
                               "begin or end with a space."),
            "CMMVC5871E": ("", "CMMVC5871E The action failed because one or " +
                               "more of the configured port names is in a " +
                               "mapping."),
            "CMMVC5924E": ("", "CMMVC5924E The FlashCopy mapping was not " +
                               "created because the source and target " +
                               "virtual disks (VDisks) are different sizes."),
            "CMMVC6303E": ("", "CMMVC6303E The create failed because the " +
                               "source and target VDisks are the same."),
            "CMMVC7050E": ("", "CMMVC7050E The command failed because at " +
                               "least one node in the I/O group does not " +
                               "support compressed VDisks."),
        }

    # Find an unused ID
    def _find_unused_id(self, d):
        ids = []
        for k, v in d.iteritems():
            ids.append(int(v["id"]))
        ids.sort()
        for index, n in enumerate(ids):
            if n > index:
                return str(index)
        return str(len(ids))

    # Check if name is valid
    def _is_invalid_name(self, name):
        if (name[0] == " ") or (name[-1] == " "):
            return True
        for c in name:
            if ((not c.isalnum()) and (c != " ") and (c != ".")
                    and (c != "-") and (c != "_")):
                return True
        return False

    # Convert argument string to dictionary
    def _cmd_to_dict(self, cmd):
        arg_list = cmd.split()
        no_param_args = [
            "autodelete",
            "autoexpand",
            "bytes",
            "compressed",
            "force",
            "nohdr",
        ]
        one_param_args = [
            "cleanrate",
            "delim",
            "filtervalue",
            "grainsize",
            "host",
            "iogrp",
            "iscsiname",
            "mdiskgrp",
            "name",
            "rsize",
            "scsi",
            "size",
            "source",
            "target",
            "unit",
            "easytier",
            "warning",
        ]

        # Handle the special case of lsnode which is a two-word command
        # Use the one word version of the command internally
        if arg_list[0] == "svcinfo" and arg_list[1] == "lsnode":
            ret = {"cmd": "lsnodecanister"}
            arg_list.pop(0)
        else:
            ret = {"cmd": arg_list[0]}

        skip = False
        for i in range(1, len(arg_list)):
            if skip:
                skip = False
                continue
            if arg_list[i][0] == "-":
                if arg_list[i][1:] in no_param_args:
                    ret[arg_list[i][1:]] = True
                elif arg_list[i][1:] in one_param_args:
                    ret[arg_list[i][1:]] = arg_list[i + 1]
                    skip = True
                else:
                    raise exception.InvalidInput(
                        reason=_('unrecognized argument %s') % arg_list[i])
            else:
                ret["obj"] = arg_list[i]
        return ret

    # Generic function for printing information
    def _print_info_cmd(self, rows, delim=" ", nohdr=False, **kwargs):
        if nohdr:
                del rows[0]

        for index in range(len(rows)):
            rows[index] = delim.join(rows[index])
        return ("%s" % "\n".join(rows), "")

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsmdiskgrp(self, **kwargs):
        rows = [None] * 3
        rows[0] = ["id", "name", "status", "mdisk_count",
                   "vdisk_count capacity", "extent_size", "free_capacity",
                   "virtual_capacity", "used_capacity", "real_capacity",
                   "overallocation", "warning", "easy_tier",
                   "easy_tier_status"]
        rows[1] = ["1", self._flags["storwize_svc_volpool_name"], "online",
                   "1", str(len(self._volumes_list)), "3.25TB", "256",
                   "3.21TB", "1.54TB", "264.97MB", "35.58GB", "47", "80",
                   "auto", "inactive"]
        rows[2] = ["2", "volpool2", "online",
                   "1", "0", "3.25TB", "256",
                   "3.21TB", "1.54TB", "264.97MB", "35.58GB", "47", "80",
                   "auto", "inactive"]
        return self._print_info_cmd(rows=rows, **kwargs)

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsnodecanister(self, **kwargs):
        rows = [None] * 3
        rows[0] = ["id", "name", "UPS_serial_number", "WWNN", "status",
                   "IO_group_id", "IO_group_name", "config_node",
                   "UPS_unique_id", "hardware", "iscsi_name", "iscsi_alias",
                   "panel_name", "enclosure_id", "canister_id",
                   "enclosure_serial_number"]
        rows[1] = ["5", "node1", "", "123456789ABCDEF0", "online", "0",
                   "io_grp0",
                   "yes", "123456789ABCDEF0", "100",
                   "iqn.1982-01.com.ibm:1234.sim.node1", "", "01-1", "1", "1",
                   "0123ABC"]
        rows[2] = ["6", "node2", "", "123456789ABCDEF1", "online", "0",
                   "io_grp0",
                   "no", "123456789ABCDEF1", "100",
                   "iqn.1982-01.com.ibm:1234.sim.node2", "", "01-2", "1", "2",
                   "0123ABC"]

        if self._next_cmd_error["lsnodecanister"] == "header_mismatch":
            rows[0].pop(2)
            self._next_cmd_error["lsnodecanister"] = ""
        if self._next_cmd_error["lsnodecanister"] == "remove_field":
            for row in rows:
                row.pop(0)
            self._next_cmd_error["lsnodecanister"] = ""

        return self._print_info_cmd(rows=rows, **kwargs)

    # Print mostly made-up stuff in the correct syntax
    def _cmd_lsportip(self, **kwargs):
        if self._next_cmd_error["lsportip"] == "ip_no_config":
            self._next_cmd_error["lsportip"] = ""
            ip_addr1 = ""
            ip_addr2 = ""
            gw = ""
        else:
            ip_addr1 = "1.234.56.78"
            ip_addr2 = "1.234.56.79"
            gw = "1.234.56.1"

        rows = [None] * 17
        rows[0] = ["id", "node_id", "node_name", "IP_address", "mask",
                   "gateway", "IP_address_6", "prefix_6", "gateway_6", "MAC",
                   "duplex", "state", "speed", "failover"]
        rows[1] = ["1", "5", "node1", ip_addr1, "255.255.255.0",
                   gw, "", "", "", "01:23:45:67:89:00", "Full",
                   "online", "1Gb/s", "no"]
        rows[2] = ["1", "5", "node1", "", "", "", "", "", "",
                   "01:23:45:67:89:00", "Full", "online", "1Gb/s", "yes"]
        rows[3] = ["2", "5", "node1", "", "", "", "", "", "",
                   "01:23:45:67:89:01", "Full", "unconfigured", "1Gb/s", "no"]
        rows[4] = ["2", "5", "node1", "", "", "", "", "", "",
                   "01:23:45:67:89:01", "Full", "unconfigured", "1Gb/s", "yes"]
        rows[5] = ["3", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "no"]
        rows[6] = ["3", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "yes"]
        rows[7] = ["4", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "no"]
        rows[8] = ["4", "5", "node1", "", "", "", "", "", "", "", "",
                   "unconfigured", "", "yes"]
        rows[9] = ["1", "6", "node2", ip_addr2, "255.255.255.0",
                   gw, "", "", "", "01:23:45:67:89:02", "Full",
                   "online", "1Gb/s", "no"]
        rows[10] = ["1", "6", "node2", "", "", "", "", "", "",
                    "01:23:45:67:89:02", "Full", "online", "1Gb/s", "yes"]
        rows[11] = ["2", "6", "node2", "", "", "", "", "", "",
                    "01:23:45:67:89:03", "Full", "unconfigured", "1Gb/s", "no"]
        rows[12] = ["2", "6", "node2", "", "", "", "", "", "",
                    "01:23:45:67:89:03", "Full", "unconfigured", "1Gb/s",
                    "yes"]
        rows[13] = ["3", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "no"]
        rows[14] = ["3", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "yes"]
        rows[15] = ["4", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "no"]
        rows[16] = ["4", "6", "node2", "", "", "", "", "", "", "", "",
                    "unconfigured", "", "yes"]

        if self._next_cmd_error["lsportip"] == "header_mismatch":
            rows[0].pop(2)
            self._next_cmd_error["lsportip"] = ""
        if self._next_cmd_error["lsportip"] == "remove_field":
            for row in rows:
                row.pop(1)
            self._next_cmd_error["lsportip"] = ""

        return self._print_info_cmd(rows=rows, **kwargs)

    # Create a vdisk
    def _cmd_mkvdisk(self, **kwargs):
        # We only save the id/uid, name, and size - all else will be made up
        volume_info = {}
        volume_info["id"] = self._find_unused_id(self._volumes_list)
        volume_info["uid"] = ("ABCDEF" * 3) + ("0" * 14) + volume_info["id"]

        if "name" in kwargs:
            volume_info["name"] = kwargs["name"].strip('\'\"')
        else:
            volume_info["name"] = "vdisk" + volume_info["id"]

        # Assume size and unit are given, store it in bytes
        capacity = int(kwargs["size"])
        unit = kwargs["unit"]

        if unit == "b":
            cap_bytes = capacity
        elif unit == "kb":
            cap_bytes = capacity * pow(1024, 1)
        elif unit == "mb":
            cap_bytes = capacity * pow(1024, 2)
        elif unit == "gb":
            cap_bytes = capacity * pow(1024, 3)
        elif unit == "tb":
            cap_bytes = capacity * pow(1024, 4)
        elif unit == "pb":
            cap_bytes = capacity * pow(1024, 5)
        volume_info["cap_bytes"] = str(cap_bytes)
        volume_info["capacity"] = str(capacity) + unit.upper()

        if "easytier" in kwargs:
            if kwargs["easytier"] == "on":
                volume_info["easy_tier"] = "on"
            else:
                volume_info["easy_tier"] = "off"

        if "rsize" in kwargs:
            # Fake numbers
            volume_info["used_capacity"] = "0.75MB"
            volume_info["real_capacity"] = "36.98MB"
            volume_info["free_capacity"] = "36.23MB"
            volume_info["used_capacity_bytes"] = "786432"
            volume_info["real_capacity_bytes"] = "38776340"
            volume_info["free_capacity_bytes"] = "37989908"
            if "warning" in kwargs:
                volume_info["warning"] = kwargs["warning"].rstrip('%')
            else:
                volume_info["warning"] = "80"
            if "autoexpand" in kwargs:
                volume_info["autoexpand"] = "on"
            else:
                volume_info["autoexpand"] = "off"
            if "grainsize" in kwargs:
                volume_info["grainsize"] = kwargs["grainsize"]
            else:
                volume_info["grainsize"] = "32"
            if "compressed" in kwargs:
                if self._next_cmd_error["mkvdisk"] == "no_compression":
                    self._next_cmd_error["mkvdisk"] = ""
                    return self._errors["CMMVC7050E"]
                volume_info["compressed_copy"] = "yes"
            else:
                volume_info["compressed_copy"] = "no"
        else:
            volume_info["used_capacity"] = volume_info["capacity"]
            volume_info["real_capacity"] = volume_info["capacity"]
            volume_info["free_capacity"] = "0.00MB"
            volume_info["used_capacity_bytes"] = volume_info["cap_bytes"]
            volume_info["real_capacity_bytes"] = volume_info["cap_bytes"]
            volume_info["free_capacity_bytes"] = "0"
            volume_info["warning"] = ""
            volume_info["autoexpand"] = ""
            volume_info["grainsize"] = ""
            volume_info["compressed_copy"] = "no"

        if volume_info["name"] in self._volumes_list:
            return self._errors["CMMVC6035E"]
        else:
            self._volumes_list[volume_info["name"]] = volume_info
            return ("Virtual Disk, id [%s], successfully created" %
                    (volume_info["id"]), "")

    # Delete a vdisk
    def _cmd_rmvdisk(self, **kwargs):
        force = 0
        if "force" in kwargs:
            force = 1

        if "obj" not in kwargs:
            return self._errors["CMMVC5701E"]
        vol_name = kwargs["obj"].strip('\'\"')

        if not vol_name in self._volumes_list:
            return self._errors["CMMVC5753E"]

        if force == 0:
            for k, mapping in self._mappings_list.iteritems():
                if mapping["vol"] == vol_name:
                    return self._errors["CMMVC5840E"]
            for k, fcmap in self._fcmappings_list.iteritems():
                if ((fcmap["source"] == vol_name) or
                        (fcmap["target"] == vol_name)):
                    return self._errors["CMMVC5840E"]

        del self._volumes_list[vol_name]
        return ("", "")

    def _get_fcmap_info(self, vol_name):
        ret_vals = {
            "fc_id": "",
            "fc_name": "",
            "fc_map_count": "0",
        }
        for k, fcmap in self._fcmappings_list.iteritems():
            if ((fcmap["source"] == vol_name) or
                    (fcmap["target"] == vol_name)):
                ret_vals["fc_id"] = fcmap["id"]
                ret_vals["fc_name"] = fcmap["name"]
                ret_vals["fc_map_count"] = "1"
        return ret_vals

    # List information about vdisks
    def _cmd_lsvdisk(self, **kwargs):
        if "obj" not in kwargs:
            rows = []
            rows.append(["id", "name", "IO_group_id", "IO_group_name",
                         "status", "mdisk_grp_id", "mdisk_grp_name",
                         "capacity", "type", "FC_id", "FC_name", "RC_id",
                         "RC_name", "vdisk_UID", "fc_map_count", "copy_count",
                         "fast_write_state", "se_copy_count", "RC_change"])

            for k, vol in self._volumes_list.iteritems():
                if (("filtervalue" not in kwargs) or
                        (kwargs["filtervalue"] == "name=" + vol["name"])):
                    fcmap_info = self._get_fcmap_info(vol["name"])

                    if "bytes" in kwargs:
                        cap = vol["cap_bytes"]
                    else:
                        cap = vol["capacity"]
                    rows.append([str(vol["id"]), vol["name"], "0", "io_grp0",
                                "online", "0",
                                self._flags["storwize_svc_volpool_name"],
                                cap, "striped",
                                fcmap_info["fc_id"], fcmap_info["fc_name"],
                                "", "", vol["uid"],
                                fcmap_info["fc_map_count"], "1", "empty",
                                "1", "no"])

            return self._print_info_cmd(rows=rows, **kwargs)

        else:
            if kwargs["obj"] not in self._volumes_list:
                return self._errors["CMMVC5754E"]
            vol = self._volumes_list[kwargs["obj"]]
            fcmap_info = self._get_fcmap_info(vol["name"])
            if "bytes" in kwargs:
                cap = vol["cap_bytes"]
                cap_u = vol["used_capacity_bytes"]
                cap_r = vol["real_capacity_bytes"]
                cap_f = vol["free_capacity_bytes"]
            else:
                cap = vol["capacity"]
                cap_u = vol["used_capacity"]
                cap_r = vol["real_capacity"]
                cap_f = vol["free_capacity"]
            rows = []

            rows.append(["id", str(vol["id"])])
            rows.append(["name", vol["name"]])
            rows.append(["IO_group_id", "0"])
            rows.append(["IO_group_name", "io_grp0"])
            rows.append(["status", "online"])
            rows.append(["mdisk_grp_id", "0"])
            rows.append(["mdisk_grp_name",
                    self._flags["storwize_svc_volpool_name"]])
            rows.append(["capacity", cap])
            rows.append(["type", "striped"])
            rows.append(["formatted", "no"])
            rows.append(["mdisk_id", ""])
            rows.append(["mdisk_name", ""])
            rows.append(["FC_id", fcmap_info["fc_id"]])
            rows.append(["FC_name", fcmap_info["fc_name"]])
            rows.append(["RC_id", ""])
            rows.append(["RC_name", ""])
            rows.append(["vdisk_UID", vol["uid"]])
            rows.append(["throttling", "0"])

            if self._next_cmd_error["lsvdisk"] == "blank_pref_node":
                rows.append(["preferred_node_id", ""])
                self._next_cmd_error["lsvdisk"] = ""
            elif self._next_cmd_error["lsvdisk"] == "no_pref_node":
                self._next_cmd_error["lsvdisk"] = ""
            else:
                rows.append(["preferred_node_id", "6"])
            rows.append(["fast_write_state", "empty"])
            rows.append(["cache", "readwrite"])
            rows.append(["udid", ""])
            rows.append(["fc_map_count", fcmap_info["fc_map_count"]])
            rows.append(["sync_rate", "50"])
            rows.append(["copy_count", "1"])
            rows.append(["se_copy_count", "0"])
            rows.append(["mirror_write_priority", "latency"])
            rows.append(["RC_change", "no"])
            rows.append(["used_capacity", cap_u])
            rows.append(["real_capacity", cap_r])
            rows.append(["free_capacity", cap_f])
            rows.append(["autoexpand", vol["autoexpand"]])
            rows.append(["warning", vol["warning"]])
            rows.append(["grainsize", vol["grainsize"]])
            rows.append(["easy_tier", vol["easy_tier"]])
            rows.append(["compressed_copy", vol["compressed_copy"]])

            if "nohdr" in kwargs:
                for index in range(len(rows)):
                    rows[index] = " ".join(rows[index][1:])

            if "delim" in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs["delim"].join(rows[index])

            return ("%s" % "\n".join(rows), "")

    # Make a host
    def _cmd_mkhost(self, **kwargs):
        host_info = {}
        host_info["id"] = self._find_unused_id(self._hosts_list)

        if "name" in kwargs:
            host_name = kwargs["name"].strip('\'\"')
        else:
            host_name = "host" + str(host_info["id"])
        host_info["host_name"] = host_name

        if "iscsiname" not in kwargs:
            return self._errors["CMMVC5707E"]
        host_info["iscsi_name"] = kwargs["iscsiname"].strip('\'\"')

        if self._is_invalid_name(host_name):
            return self._errors["CMMVC6527E"]

        if host_name in self._hosts_list:
            return self._errors["CMMVC6035E"]

        for k, v in self._hosts_list.iteritems():
            if v["iscsi_name"] == host_info["iscsi_name"]:
                return self._errors["CMMVC6581E"]

        self._hosts_list[host_name] = host_info
        return ("Host, id [%s], successfully created" %
                (host_info["id"]), "")

    # Remove a host
    def _cmd_rmhost(self, **kwargs):
        if "obj" not in kwargs:
            return self._errors["CMMVC5701E"]

        host_name = kwargs["obj"].strip('\'\"')
        if host_name not in self._hosts_list:
            return self._errors["CMMVC5753E"]

        for k, v in self._mappings_list.iteritems():
            if (v["host"] == host_name):
                return self._errors["CMMVC5871E"]

        del self._hosts_list[host_name]
        return ("", "")

    # List information about hosts
    def _cmd_lshost(self, **kwargs):
        if "obj" not in kwargs:
            rows = []
            rows.append(["id", "name", "port_count", "iogrp_count", "status"])

            found = False
            for k, host in self._hosts_list.iteritems():
                filterstr = "name=" + host["host_name"]
                if (("filtervalue" not in kwargs) or
                        (kwargs["filtervalue"] == filterstr)):
                    rows.append([host["id"], host["host_name"], "1", "4",
                                "offline"])
                    found = True
            if found:
                return self._print_info_cmd(rows=rows, **kwargs)
            else:
                return ("", "")
        else:
            if kwargs["obj"] not in self._hosts_list:
                return self._errors["CMMVC5754E"]
            host = self._hosts_list[kwargs["obj"]]
            rows = []
            rows.append(["id", host["id"]])
            rows.append(["name", host["host_name"]])
            rows.append(["port_count", "1"])
            rows.append(["type", "generic"])
            rows.append(["mask", "1111"])
            rows.append(["iogrp_count", "4"])
            rows.append(["status", "offline"])
            rows.append(["iscsi_name", host["iscsi_name"]])
            rows.append(["node_logged_in_count", "0"])
            rows.append(["state", "offline"])

            if "nohdr" in kwargs:
                for index in range(len(rows)):
                    rows[index] = " ".join(rows[index][1:])

            if "delim" in kwargs:
                for index in range(len(rows)):
                    rows[index] = kwargs["delim"].join(rows[index])

            return ("%s" % "\n".join(rows), "")

    # Create a vdisk-host mapping
    def _cmd_mkvdiskhostmap(self, **kwargs):
        mapping_info = {}
        mapping_info["id"] = self._find_unused_id(self._mappings_list)

        if "host" not in kwargs:
            return self._errors["CMMVC5707E"]
        mapping_info["host"] = kwargs["host"].strip('\'\"')

        if "scsi" not in kwargs:
            return self._errors["CMMVC5707E"]
        mapping_info["lun"] = kwargs["scsi"].strip('\'\"')

        if "obj" not in kwargs:
            return self._errors["CMMVC5707E"]
        mapping_info["vol"] = kwargs["obj"].strip('\'\"')

        if not mapping_info["vol"] in self._volumes_list:
            return self._errors["CMMVC5753E"]

        if not mapping_info["host"] in self._hosts_list:
            return self._errors["CMMVC5754E"]

        if mapping_info["vol"] in self._mappings_list:
            return self._errors["CMMVC6071E"]

        for k, v in self._mappings_list.iteritems():
            if ((v["host"] == mapping_info["host"]) and
                    (v["lun"] == mapping_info["lun"])):
                return self._errors["CMMVC5879E"]

        self._mappings_list[mapping_info["vol"]] = mapping_info
        return ("Virtual Disk to Host map, id [%s], successfully created"
                % (mapping_info["id"]), "")

    # Delete a vdisk-host mapping
    def _cmd_rmvdiskhostmap(self, **kwargs):
        if "host" not in kwargs:
            return self._errors["CMMVC5707E"]
        host = kwargs["host"].strip('\'\"')

        if "obj" not in kwargs:
            return self._errors["CMMVC5701E"]
        vol = kwargs["obj"].strip('\'\"')

        if not vol in self._mappings_list:
            return self._errors["CMMVC5753E"]

        if self._mappings_list[vol]["host"] != host:
            return self._errors["CMMVC5753E"]

        del self._mappings_list[vol]
        return ("", "")

    # List information about vdisk-host mappings
    def _cmd_lshostvdiskmap(self, **kwargs):
        index = 1
        no_hdr = 0
        delimeter = ""
        host_name = kwargs["obj"]

        if host_name not in self._hosts_list:
            return self._errors["CMMVC5754E"]

        rows = []
        rows.append(["id", "name", "SCSI_id", "vdisk_id", "vdisk_name",
                     "vdisk_UID"])

        for k, mapping in self._mappings_list.iteritems():
            if (host_name == "") or (mapping["host"] == host_name):
                volume = self._volumes_list[mapping["vol"]]
                rows.append([mapping["id"], mapping["host"],
                            mapping["lun"], volume["id"],
                            volume["name"], volume["uid"]])

        return self._print_info_cmd(rows=rows, **kwargs)

    # Create a FlashCopy mapping
    def _cmd_mkfcmap(self, **kwargs):
        source = ""
        target = ""

        if "source" not in kwargs:
            return self._errors["CMMVC5707E"]
        source = kwargs["source"].strip('\'\"')
        if not source in self._volumes_list:
            return self._errors["CMMVC5754E"]

        if "target" not in kwargs:
            return self._errors["CMMVC5707E"]
        target = kwargs["target"].strip('\'\"')
        if not target in self._volumes_list:
            return self._errors["CMMVC5754E"]

        if source == target:
            return self._errors["CMMVC6303E"]

        if (self._volumes_list[source]["cap_bytes"] !=
                self._volumes_list[target]["cap_bytes"]):
            return self._errors["CMMVC5924E"]

        fcmap_info = {}
        fcmap_info["source"] = source
        fcmap_info["target"] = target
        fcmap_info["id"] = self._find_unused_id(self._fcmappings_list)
        fcmap_info["name"] = "fcmap" + fcmap_info["id"]
        fcmap_info["status"] = "idle_or_copied"
        fcmap_info["progress"] = "0"
        self._fcmappings_list[target] = fcmap_info

        return("FlashCopy Mapping, id [" + fcmap_info["id"] +
               "], successfully created", "")

    # Same function used for both prestartfcmap and startfcmap
    def _cmd_gen_startfcmap(self, mode, **kwargs):
        if "obj" not in kwargs:
            return self._errors["CMMVC5701E"]
        id_num = kwargs["obj"]

        if mode == "pre":
            if self._next_cmd_error["prestartfcmap"] == "bad_id":
                id_num = -1
                self._next_cmd_error["prestartfcmap"] = ""
        else:
            if self._next_cmd_error["startfcmap"] == "bad_id":
                id_num = -1
                self._next_cmd_error["startfcmap"] = ""

        for k, fcmap in self._fcmappings_list.iteritems():
            if fcmap["id"] == id_num:
                if mode == "pre":
                    fcmap["status"] = "preparing"
                else:
                    fcmap["status"] = "copying"
                fcmap["progress"] = "0"
                return ("", "")
        return self._errors["CMMVC5753E"]

    # Same function used for both stopfcmap and rmfcmap
    # Assumes it is called with "-force <fc_map_id>"
    def _cmd_stoprmfcmap(self, mode, **kwargs):
        if "obj" not in kwargs:
            return self._errors["CMMVC5701E"]
        id_num = kwargs["obj"]

        if self._next_cmd_error["rmfcmap"] == "bad_id":
            id_num = -1
            self._next_cmd_error["rmfcmap"] = ""

        to_delete = None
        found = False
        for k, fcmap in self._fcmappings_list.iteritems():
            if fcmap["id"] == id_num:
                found = True
                if mode == "rm":
                    to_delete = k

        if to_delete:
            del self._fcmappings_list[to_delete]

        if found:
            return ("", "")
        else:
            return self._errors["CMMVC5753E"]

    def _cmd_lsfcmap(self, **kwargs):
        rows = []
        rows.append(["id", "name", "source_vdisk_id", "source_vdisk_name",
                     "target_vdisk_id", "target_vdisk_name", "group_id",
                     "group_name", "status", "progress", "copy_rate",
                     "clean_progress", "incremental", "partner_FC_id",
                     "partner_FC_name", "restoring", "start_time",
                     "rc_controlled"])

        # Assume we always get a filtervalue argument
        filter_key = kwargs["filtervalue"].split("=")[0]
        filter_value = kwargs["filtervalue"].split("=")[1]
        to_delete = []
        for k, v in self._fcmappings_list.iteritems():
            if str(v[filter_key]) == filter_value:
                source = self._volumes_list[v["source"]]
                target = self._volumes_list[v["target"]]
                old_status = v["status"]
                if old_status == "preparing":
                    new_status = "prepared"
                    if self._next_cmd_error["lsfcmap"] == "bogus_prepare":
                        new_status = "bogus"
                elif (old_status == "copying") and (v["progress"] == "0"):
                    new_status = "copying"
                    v["progress"] = "50"
                elif (old_status == "copying") and (v["progress"] == "50"):
                    new_status = "idle_or_copied"
                    to_delete.append(k)
                else:
                    new_status = old_status
                v["status"] = new_status

                if ((self._next_cmd_error["lsfcmap"] == "speed_up") or
                        (self._next_cmd_error["lsfcmap"] == "bogus_prepare")):
                    print_status = new_status
                    self._next_cmd_error["lsfcmap"] = ""
                else:
                    print_status = old_status

                rows.append([v["id"], v["name"], source["id"],
                            source["name"], target["id"], target["name"], "",
                            "", print_status, v["progress"], "50", "100",
                            "off", "", "", "no", "", "no"])

        for d in to_delete:
            del self._fcmappings_list[k]

        return self._print_info_cmd(rows=rows, **kwargs)

    # The main function to run commands on the management simulator
    def execute_command(self, cmd, check_exit_code=True):
        try:
            kwargs = self._cmd_to_dict(cmd)
        except IndexError:
            return self._errors["CMMVC5707E"]

        command = kwargs["cmd"]
        del kwargs["cmd"]
        arg_list = cmd.split()

        if command == "lsmdiskgrp":
            out, err = self._cmd_lsmdiskgrp(**kwargs)
        elif command == "lsnodecanister":
            out, err = self._cmd_lsnodecanister(**kwargs)
        elif command == "lsportip":
            out, err = self._cmd_lsportip(**kwargs)
        elif command == "mkvdisk":
            out, err = self._cmd_mkvdisk(**kwargs)
        elif command == "rmvdisk":
            out, err = self._cmd_rmvdisk(**kwargs)
        elif command == "lsvdisk":
            out, err = self._cmd_lsvdisk(**kwargs)
        elif command == "mkhost":
            out, err = self._cmd_mkhost(**kwargs)
        elif command == "rmhost":
            out, err = self._cmd_rmhost(**kwargs)
        elif command == "lshost":
            out, err = self._cmd_lshost(**kwargs)
        elif command == "mkvdiskhostmap":
            out, err = self._cmd_mkvdiskhostmap(**kwargs)
        elif command == "rmvdiskhostmap":
            out, err = self._cmd_rmvdiskhostmap(**kwargs)
        elif command == "lshostvdiskmap":
            out, err = self._cmd_lshostvdiskmap(**kwargs)
        elif command == "mkfcmap":
            out, err = self._cmd_mkfcmap(**kwargs)
        elif command == "prestartfcmap":
            out, err = self._cmd_gen_startfcmap(mode="pre", **kwargs)
        elif command == "startfcmap":
            out, err = self._cmd_gen_startfcmap(mode="start", **kwargs)
        elif command == "stopfcmap":
            out, err = self._cmd_stoprmfcmap(mode="stop", **kwargs)
        elif command == "rmfcmap":
            out, err = self._cmd_stoprmfcmap(mode="rm", **kwargs)
        elif command == "lsfcmap":
            out, err = self._cmd_lsfcmap(**kwargs)
        else:
            out, err = ("", "ERROR: Unsupported command")

        if (check_exit_code) and (len(err) != 0):
            raise exception.ProcessExecutionError(exit_code=1,
                                                  stdout=out,
                                                  stderr=err,
                                                  cmd=' '.join(cmd))

        return (out, err)

    # After calling this function, the next call to the specified command will
    # result in in the error specified
    def error_injection(self, cmd, error):
        self._next_cmd_error[cmd] = error


class StorwizeSVCFakeDriver(storwize_svc.StorwizeSVCDriver):
    def __init__(self, *args, **kwargs):
        super(StorwizeSVCFakeDriver, self).__init__(*args, **kwargs)

    def set_fake_storage(self, fake):
        self.fake_storage = fake

    def _run_ssh(self, cmd, check_exit_code=True):
        try:
            LOG.debug(_('Run CLI command: %s') % cmd)
            ret = self.fake_storage.execute_command(cmd, check_exit_code)
            (stdout, stderr) = ret
            LOG.debug(_('CLI output:\n stdout: %(out)s\n stderr: %(err)s') %
                        {'out': stdout, 'err': stderr})

        except exception.ProcessExecutionError as e:
            with excutils.save_and_reraise_exception():
                LOG.debug(_('CLI Exception output:\n stdout: %(out)s\n '
                            'stderr: %(err)s') % {'out': e.stdout,
                            'err': e.stderr})

        return ret


class StorwizeSVCDriverTestCase(test.TestCase):
    def setUp(self):
        super(StorwizeSVCDriverTestCase, self).setUp()
        self.USESIM = 1
        if self.USESIM == 1:
            self.flags(
                san_ip="hostname",
                san_login="user",
                san_password="pass",
                storwize_svc_flashcopy_timeout="20",
            )
            self.sim = StorwizeSVCManagementSimulator("volpool")
            self.driver = StorwizeSVCFakeDriver()
            self.driver.set_fake_storage(self.sim)
        else:
            self.flags(
                san_ip="-1.-1.-1.-1",
                san_login="user",
                san_password="password",
                storwize_svc_volpool_name="pool",
            )
            self.driver = storwize_svc.StorwizeSVCDriver()

        self.driver.do_setup(None)
        self.driver.check_for_setup_error()

    def test_storwize_svc_volume_tests(self):
        self.flags(storwize_svc_vol_rsize="-1")
        volume = {}
        volume["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume["size"] = 10
        volume["id"] = 1
        self.driver.create_volume(volume)
        # Make sure that the volume has been created
        is_volume_defined = self.driver._is_volume_defined(volume["name"])
        self.assertEqual(is_volume_defined, True)
        self.driver.delete_volume(volume)

        if self.USESIM == 1:
            self.flags(storwize_svc_vol_rsize="2%")
            self.flags(storwize_svc_vol_compression=True)
            self.driver.create_volume(volume)
            is_volume_defined = self.driver._is_volume_defined(volume["name"])
            self.assertEqual(is_volume_defined, True)
            self.driver.delete_volume(volume)
            FLAGS.reset()

    def test_storwize_svc_ip_connectivity(self):
        # Check for missing san_ip
        self.flags(san_ip=None)
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)

        if self.USESIM != 1:
            # Check for invalid ip
            self.flags(san_ip="-1.-1.-1.-1")
            self.assertRaises(socket.gaierror,
                        self.driver.check_for_setup_error)

            # Check for unreachable IP
            self.flags(san_ip="1.1.1.1")
            self.assertRaises(socket.error,
                        self.driver.check_for_setup_error)

    def test_storwize_svc_connectivity(self):
        # Make sure we detect if the pool doesn't exist
        no_exist_pool = "i-dont-exist-%s" % random.randint(10000, 99999)
        self.flags(storwize_svc_volpool_name=no_exist_pool)
        self.assertRaises(exception.InvalidInput,
                self.driver.check_for_setup_error)
        FLAGS.reset()

        # Check the case where the user didn't configure IP addresses
        # as well as receiving unexpected results from the storage
        if self.USESIM == 1:
            self.sim.error_injection("lsnodecanister", "header_mismatch")
            self.assertRaises(exception.VolumeBackendAPIException,
                    self.driver.check_for_setup_error)
            self.sim.error_injection("lsnodecanister", "remove_field")
            self.assertRaises(exception.VolumeBackendAPIException,
                    self.driver.check_for_setup_error)
            self.sim.error_injection("lsportip", "ip_no_config")
            self.assertRaises(exception.VolumeBackendAPIException,
                    self.driver.check_for_setup_error)
            self.sim.error_injection("lsportip", "header_mismatch")
            self.assertRaises(exception.VolumeBackendAPIException,
                    self.driver.check_for_setup_error)
            self.sim.error_injection("lsportip", "remove_field")
            self.assertRaises(exception.VolumeBackendAPIException,
                    self.driver.check_for_setup_error)

        # Check with bad parameters
        self.flags(san_password=None)
        self.flags(san_private_key=None)
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        self.flags(storwize_svc_vol_rsize="invalid")
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        self.flags(storwize_svc_vol_warning="invalid")
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        self.flags(storwize_svc_vol_autoexpand="invalid")
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        self.flags(storwize_svc_vol_grainsize=str(42))
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        self.flags(storwize_svc_flashcopy_timeout=str(601))
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        self.flags(storwize_svc_vol_compression=True)
        self.flags(storwize_svc_vol_rsize="-1")
        self.assertRaises(exception.InvalidInput,
                self.driver._check_flags)
        FLAGS.reset()

        # Finally, check with good parameters
        self.driver.check_for_setup_error()

    def test_storwize_svc_flashcopy(self):
        volume1 = {}
        volume1["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume1["size"] = 10
        volume1["id"] = 10
        self.driver.create_volume(volume1)

        snapshot = {}
        snapshot["name"] = "snap_volume%s" % random.randint(10000, 99999)
        snapshot["volume_name"] = volume1["name"]

        # Test timeout and volume cleanup
        self.flags(storwize_svc_flashcopy_timeout=str(1))
        self.assertRaises(exception.InvalidSnapshot,
                self.driver.create_snapshot, snapshot)
        is_volume_defined = self.driver._is_volume_defined(snapshot["name"])
        self.assertEqual(is_volume_defined, False)
        FLAGS.reset()

        # Test bogus statuses
        if self.USESIM == 1:
            self.sim.error_injection("lsfcmap", "bogus_prepare")
            self.assertRaises(exception.VolumeBackendAPIException,
                self.driver.create_snapshot, snapshot)

        # Test prestartfcmap, startfcmap, and rmfcmap failing
        if self.USESIM == 1:
            self.sim.error_injection("prestartfcmap", "bad_id")
            self.assertRaises(exception.ProcessExecutionError,
                self.driver.create_snapshot, snapshot)
            self.sim.error_injection("lsfcmap", "speed_up")
            self.sim.error_injection("startfcmap", "bad_id")
            self.assertRaises(exception.ProcessExecutionError,
                self.driver.create_snapshot, snapshot)
            self.sim.error_injection("prestartfcmap", "bad_id")
            self.sim.error_injection("rmfcmap", "bad_id")
            self.assertRaises(exception.ProcessExecutionError,
                self.driver.create_snapshot, snapshot)

        # Test successful snapshot
        self.driver.create_snapshot(snapshot)

        # Ensure snapshot is defined
        is_volume_defined = self.driver._is_volume_defined(snapshot["name"])
        self.assertEqual(is_volume_defined, True)

        # Try to create a snapshot from an non-existing volume - should fail
        snapshot2 = {}
        snapshot2["name"] = "snap_volume%s" % random.randint(10000, 99999)
        snapshot2["volume_name"] = "undefined-vol"
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.create_snapshot,
                          snapshot2)

        # Create volume from snapshot
        volume2 = {}
        volume2["name"] = "snap2vol_volume%s" % random.randint(10000, 99999)

        # Create volume from snapshot into an existsing volume
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.create_volume_from_snapshot,
                          volume1,
                          snapshot)

        # Try to create a volume from a non-existing snapshot
        self.assertRaises(exception.SnapshotNotFound,
                          self.driver.create_volume_from_snapshot,
                          volume2,
                          snapshot2)

        # Fail the snapshot
        if self.USESIM == 1:
            self.sim.error_injection("prestartfcmap", "bad_id")
            self.assertRaises(exception.ProcessExecutionError,
                self.driver.create_volume_from_snapshot, volume2, snapshot)

        # Succeed
        if self.USESIM == 1:
            self.sim.error_injection("lsfcmap", "speed_up")
        self.driver.create_volume_from_snapshot(volume2, snapshot)

        # Ensure volume is defined
        is_volume_defined = self.driver._is_volume_defined(volume2["name"])
        self.assertEqual(is_volume_defined, True)

        self.driver._delete_volume(volume2, True)
        self.driver._delete_snapshot(snapshot, True)

        # Check with target with different size
        volume3 = {}
        volume3["name"] = "test3_volume%s" % random.randint(10000, 99999)
        volume3["size"] = 11
        volume3["id"] = 11
        self.driver.create_volume(volume3)
        snapshot["name"] = volume3["name"]
        self.assertRaises(exception.InvalidSnapshot,
                self.driver.create_snapshot, snapshot)
        self.driver._delete_volume(volume1, True)
        self.driver._delete_volume(volume3, True)

        # Snapshot volume that doesn't exist
        snapshot = {}
        snapshot["name"] = "snap_volume%s" % random.randint(10000, 99999)
        snapshot["volume_name"] = "no_exist"
        self.assertRaises(exception.VolumeNotFound,
                self.driver.create_snapshot, snapshot)

    def test_storwize_svc_volumes(self):
        # Create a first volume
        volume = {}
        volume["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume["size"] = 10
        volume["id"] = 1

        self.driver.create_volume(volume)

        self.driver.ensure_export(None, volume)

        # Do nothing
        self.driver.create_export(None, volume)
        self.driver.remove_export(None, volume)
        self.assertRaises(NotImplementedError,
                self.driver.check_for_export, None, volume["id"])

        # Make sure volume attributes are as they should be
        attributes = self.driver._get_volume_attributes(volume["name"])
        attr_size = float(attributes["capacity"]) / 1073741824  # bytes to GB
        self.assertEqual(attr_size, float(volume["size"]))
        pool = storwize_svc.FLAGS.storwize_svc_volpool_name
        self.assertEqual(attributes["mdisk_grp_name"], pool)

        # Try to create the volume again (should fail)
        self.assertRaises(exception.ProcessExecutionError,
                self.driver.create_volume, volume)

        # Try to delete a volume that doesn't exist (should not fail)
        vol_no_exist = {"name": "i_dont_exist"}
        self.driver.delete_volume(vol_no_exist)
        # Ensure export for volume that doesn't exist (should not fail)
        self.driver.ensure_export(None, vol_no_exist)

        # Delete the volume
        self.driver.delete_volume(volume)

    def _create_test_vol(self):
        volume = {}
        volume["name"] = "testparam_volume%s" % random.randint(10000, 99999)
        volume["size"] = 1
        volume["id"] = 1
        self.driver.create_volume(volume)

        attrs = self.driver._get_volume_attributes(volume["name"])
        self.driver.delete_volume(volume)
        return attrs

    def test_storwize_svc_volume_params(self):
        # Option test matrix
        # Option        Value   Covered by test #
        # rsize         -1      1
        # rsize         2%      2,3
        # warning       0       2
        # warning       80%     3
        # autoexpand    True    2
        # autoexpand    False   3
        # grainsize     32      2
        # grainsize     256     3
        # compression   True    4
        # compression   False   2,3
        # easytier      True    1,3
        # easytier      False   2

        # Test 1
        self.flags(storwize_svc_vol_rsize="-1")
        self.flags(storwize_svc_vol_easytier=True)
        attrs = self._create_test_vol()
        self.assertEquals(attrs["free_capacity"], "0")
        self.assertEquals(attrs["easy_tier"], "on")
        FLAGS.reset()

        # Test 2
        self.flags(storwize_svc_vol_rsize="2%")
        self.flags(storwize_svc_vol_compression=False)
        self.flags(storwize_svc_vol_warning="0")
        self.flags(storwize_svc_vol_autoexpand=True)
        self.flags(storwize_svc_vol_grainsize="32")
        self.flags(storwize_svc_vol_easytier=False)
        attrs = self._create_test_vol()
        self.assertNotEqual(attrs["capacity"], attrs["real_capacity"])
        self.assertEquals(attrs["compressed_copy"], "no")
        self.assertEquals(attrs["warning"], "0")
        self.assertEquals(attrs["autoexpand"], "on")
        self.assertEquals(attrs["grainsize"], "32")
        self.assertEquals(attrs["easy_tier"], "off")
        FLAGS.reset()

        # Test 3
        self.flags(storwize_svc_vol_rsize="2%")
        self.flags(storwize_svc_vol_compression=False)
        self.flags(storwize_svc_vol_warning="80%")
        self.flags(storwize_svc_vol_autoexpand=False)
        self.flags(storwize_svc_vol_grainsize="256")
        self.flags(storwize_svc_vol_easytier=True)
        attrs = self._create_test_vol()
        self.assertNotEqual(attrs["capacity"], attrs["real_capacity"])
        self.assertEquals(attrs["compressed_copy"], "no")
        self.assertEquals(attrs["warning"], "80")
        self.assertEquals(attrs["autoexpand"], "off")
        self.assertEquals(attrs["grainsize"], "256")
        self.assertEquals(attrs["easy_tier"], "on")
        FLAGS.reset()

        # Test 4
        self.flags(storwize_svc_vol_rsize="2%")
        self.flags(storwize_svc_vol_compression=True)
        try:
            attrs = self._create_test_vol()
            self.assertNotEqual(attrs["capacity"], attrs["real_capacity"])
            self.assertEquals(attrs["compressed_copy"], "yes")
        except exception.ProcessExecutionError as e:
            if "CMMVC7050E" not in e.stderr:
                raise exception.ProcessExecutionError(exit_code=e.exit_code,
                                                      stdout=e.stdout,
                                                      stderr=e.stderr,
                                                      cmd=e.cmd)
        if self.USESIM == 1:
            self.sim.error_injection("mkvdisk", "no_compression")
            self.assertRaises(exception.ProcessExecutionError,
                    self._create_test_vol)
        FLAGS.reset()

    def test_storwize_svc_unicode_host_and_volume_names(self):
        volume1 = {}
        volume1["name"] = u"unicode1_volume%s" % random.randint(10000, 99999)
        volume1["size"] = 2
        volume1["id"] = 1
        self.driver.create_volume(volume1)
        # Make sure that the volumes have been created
        is_volume_defined = self.driver._is_volume_defined(volume1["name"])
        self.assertEqual(is_volume_defined, True)
        conn = {}
        conn["initiator"] = u"unicode:init:%s" % random.randint(10000, 99999)
        conn["ip"] = "10.10.10.10"  # Bogus ip for testing
        self.driver.initialize_connection(volume1, conn)
        self.driver.terminate_connection(volume1, conn)
        self.driver.delete_volume(volume1)

    def test_storwize_svc_host_maps(self):
        # Create two volumes to be used in mappings
        volume1 = {}
        volume1["name"] = "test1_volume%s" % random.randint(10000, 99999)
        volume1["size"] = 2
        volume1["id"] = 1
        self.driver.create_volume(volume1)
        volume2 = {}
        volume2["name"] = "test2_volume%s" % random.randint(10000, 99999)
        volume2["size"] = 2
        volume2["id"] = 1
        self.driver.create_volume(volume2)

        # Check case where no hosts exist
        if self.USESIM == 1:
            ret = self.driver._get_host_from_iscsiname("foo")
            self.assertEquals(ret, None)
            ret = self.driver._is_host_defined("foo")
            self.assertEquals(ret, False)

        # Make sure that the volumes have been created
        is_volume_defined = self.driver._is_volume_defined(volume1["name"])
        self.assertEqual(is_volume_defined, True)
        is_volume_defined = self.driver._is_volume_defined(volume2["name"])
        self.assertEqual(is_volume_defined, True)

        # Initialize connection from the first volume to a host
        # Add some characters to the initiator name that should be converted
        # when used for the host name
        conn = {}
        conn["initiator"] = "test:init:%s" % random.randint(10000, 99999)
        conn["ip"] = "10.10.10.10"  # Bogus ip for testing
        self.driver.initialize_connection(volume1, conn)

        # Initialize again, should notice it and do nothing
        self.driver.initialize_connection(volume1, conn)

        # Try to delete the 1st volume (should fail because it is mapped)
        self.assertRaises(exception.ProcessExecutionError,
                self.driver.delete_volume, volume1)

        # Test no preferred node
        self.driver.terminate_connection(volume1, conn)
        if self.USESIM == 1:
            self.sim.error_injection("lsvdisk", "no_pref_node")
            self.driver.initialize_connection(volume1, conn)

        # Initialize connection from the second volume to the host with no
        # preferred node set if in simulation mode, otherwise, just
        # another initialize connection.
        if self.USESIM == 1:
            self.sim.error_injection("lsvdisk", "blank_pref_node")
        self.driver.initialize_connection(volume2, conn)

        # Try to remove connection from host that doesn't exist (should fail)
        conn_no_exist = {"initiator": "i_dont_exist"}
        self.assertRaises(exception.VolumeBackendAPIException,
                self.driver.terminate_connection, volume1, conn_no_exist)

        # Try to remove connection from volume that isn't mapped (should print
        # message but NOT fail)
        vol_no_exist = {"name": "i_dont_exist"}
        self.driver.terminate_connection(vol_no_exist, conn)

        # Remove the mapping from the 1st volume and delete it
        self.driver.terminate_connection(volume1, conn)
        self.driver.delete_volume(volume1)
        vol_def = self.driver._is_volume_defined(volume1["name"])
        self.assertEqual(vol_def, False)

        # Make sure our host still exists
        host_name = self.driver._get_host_from_iscsiname(conn["initiator"])
        host_def = self.driver._is_host_defined(host_name)
        self.assertEquals(host_def, True)

        # Remove the mapping from the 2nd volume and delete it. The host should
        # be automatically removed because there are no more mappings.
        self.driver.terminate_connection(volume2, conn)
        self.driver.delete_volume(volume2)
        vol_def = self.driver._is_volume_defined(volume2["name"])
        self.assertEqual(vol_def, False)

        # Check if our host still exists (it should not)
        ret = self.driver._get_host_from_iscsiname(conn["initiator"])
        self.assertEquals(ret, None)
        ret = self.driver._is_host_defined(host_name)
        self.assertEquals(ret, False)
