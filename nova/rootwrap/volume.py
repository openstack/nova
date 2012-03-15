# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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


from nova.rootwrap import filters

filterlist = [
    # nova/volume/iscsi.py: iscsi_helper '--op' ...
    filters.CommandFilter("/usr/sbin/ietadm", "root"),
    filters.CommandFilter("/usr/sbin/tgtadm", "root"),

    # nova/volume/driver.py: 'vgs', '--noheadings', '-o', 'name'
    filters.CommandFilter("/sbin/vgs", "root"),

    # nova/volume/driver.py: 'lvcreate', '-L', sizestr, '-n', volume_name,..
    # nova/volume/driver.py: 'lvcreate', '-L', ...
    filters.CommandFilter("/sbin/lvcreate", "root"),

    # nova/volume/driver.py: 'dd', 'if=%s' % srcstr, 'of=%s' % deststr,...
    filters.CommandFilter("/bin/dd", "root"),

    # nova/volume/driver.py: 'lvremove', '-f', "%s/%s" % ...
    filters.CommandFilter("/sbin/lvremove", "root"),

    # nova/volume/driver.py: 'lvdisplay', '--noheading', '-C', '-o', 'Attr',..
    filters.CommandFilter("/sbin/lvdisplay", "root"),

    # nova/volume/driver.py: 'iscsiadm', '-m', 'discovery', '-t',...
    # nova/volume/driver.py: 'iscsiadm', '-m', 'node', '-T', ...
    filters.CommandFilter("/sbin/iscsiadm", "root"),
    ]
