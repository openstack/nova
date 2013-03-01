# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM Corp.
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

from nova import exception


class PowerVMConnectionFailed(exception.NovaException):
    message = _('Connection to PowerVM manager failed')


class PowerVMFileTransferFailed(exception.NovaException):
    message = _("File '%(file_path)s' transfer to PowerVM manager failed")


class PowerVMFTPTransferFailed(PowerVMFileTransferFailed):
    message = _("FTP %(ftp_cmd)s from %(source_path)s to %(dest_path)s failed")


class PowerVMLPARInstanceNotFound(exception.InstanceNotFound):
    message = _("LPAR instance '%(instance_name)s' could not be found")


class PowerVMLPARCreationFailed(exception.NovaException):
    message = _("LPAR instance '%(instance_name)s' creation failed")


class PowerVMNoSpaceLeftOnVolumeGroup(exception.NovaException):
    message = _("No space left on any volume group")


class PowerVMLPARAttributeNotFound(exception.NovaException):
    pass


class PowerVMLPAROperationTimeout(exception.NovaException):
    message = _("Operation '%(operation)s' on "
                "LPAR '%(instance_name)s' timed out")


class PowerVMImageCreationFailed(exception.NovaException):
    message = _("Image creation failed on PowerVM")


class PowerVMInsufficientFreeMemory(exception.NovaException):
    message = _("Insufficient free memory on PowerVM system to spawn instance "
                "'%(instance_name)s'")


class PowerVMInsufficientCPU(exception.NovaException):
    message = _("Insufficient available CPUs on PowerVM system to spawn "
                "instance '%(instance_name)s'")


class PowerVMLPARInstanceCleanupFailed(exception.NovaException):
    message = _("PowerVM LPAR instance '%(instance_name)s' cleanup failed")
