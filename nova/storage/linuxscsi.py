# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Generic linux scsi subsystem utilities."""

from nova.openstack.common.gettextutils import _
from nova.openstack.common.gettextutils import _LW
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.openstack.common import processutils
from nova import utils

LOG = logging.getLogger(__name__)


def echo_scsi_command(path, content):
    """Used to echo strings to scsi subsystem."""
    args = ["-a", path]
    kwargs = dict(process_input=content, run_as_root=True)
    utils.execute('tee', *args, **kwargs)


def rescan_hosts(hbas):
    for hba in hbas:
        echo_scsi_command("/sys/class/scsi_host/%s/scan"
                          % hba['host_device'], "- - -")


def get_device_list():
    (out, err) = utils.execute('sginfo', '-r', run_as_root=True)
    devices = []
    if out:
        line = out.strip()
        devices = line.split(" ")

    return devices


def get_device_info(device):
    (out, err) = utils.execute('sg_scan', device, run_as_root=True)
    dev_info = {'device': device, 'host': None,
                'channel': None, 'id': None, 'lun': None}
    if out:
        line = out.strip()
        line = line.replace(device + ": ", "")
        info = line.split(" ")

        for item in info:
            if '=' in item:
                pair = item.split('=')
                dev_info[pair[0]] = pair[1]
            elif 'scsi' in item:
                dev_info['host'] = item.replace('scsi', '')

    return dev_info


def _wait_for_remove(device, tries):
    tries = tries + 1
    LOG.debug(_("Trying (%(tries)s) to remove device %(device)s")
              % {'tries': tries, 'device': device["device"]})

    path = "/sys/bus/scsi/drivers/sd/%s:%s:%s:%s/delete"
    echo_scsi_command(path % (device["host"], device["channel"],
                              device["id"], device["lun"]),
                      "1")

    devices = get_device_list()
    if device["device"] not in devices:
        raise loopingcall.LoopingCallDone()


def remove_device(device):
    tries = 0
    timer = loopingcall.FixedIntervalLoopingCall(_wait_for_remove, device,
                                                 tries)
    timer.start(interval=2).wait()
    timer.stop()


def find_multipath_device(device):
    """Try and discover the multipath device for a volume."""
    mdev = None
    devices = []
    out = None
    try:
        (out, err) = utils.execute('multipath', '-l', device,
                               run_as_root=True)
    except processutils.ProcessExecutionError as exc:
        LOG.warn(_LW("Multipath call failed exit (%(code)s)")
                 % {'code': exc.exit_code})
        return None

    if out:
        lines = out.strip()
        lines = lines.split("\n")
        if lines:
            line = lines[0]
            info = line.split(" ")
            # device line output is different depending
            # on /etc/multipath.conf settings.
            if info[1][:2] == "dm":
                mdev_id = info[0]
                mdev = '/dev/mapper/%s' % mdev_id
            elif info[2][:2] == "dm":
                mdev_id = info[1].replace('(', '')
                mdev_id = mdev_id.replace(')', '')
                mdev = '/dev/mapper/%s' % mdev_id

            if mdev is None:
                LOG.warn(_LW("Couldn't find multipath device %s"), line)
                return None

            LOG.debug(_("Found multipath device = %s"), mdev)
            device_lines = lines[3:]
            for dev_line in device_lines:
                if dev_line.find("policy") != -1:
                    continue
                if '#' in dev_line:
                    LOG.warn(_LW('Skip faulty line "%(dev_line)s" of'
                                 ' multipath device %(mdev)s')
                             % {'mdev': mdev, 'dev_line': dev_line})
                    continue

                dev_line = dev_line.lstrip(' |-`')
                dev_info = dev_line.split()
                address = dev_info[0].split(":")

                dev = {'device': '/dev/%s' % dev_info[1],
                       'host': address[0], 'channel': address[1],
                       'id': address[2], 'lun': address[3]
                      }

                devices.append(dev)

    if mdev is not None:
        info = {"device": mdev,
                "id": mdev_id,
                "devices": devices}
        return info
    return None
