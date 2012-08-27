# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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


"""PowerVM manager commands."""


class BaseCommand(object):

    def lsvg(self, args=''):
        return 'lsvg %s' % args

    def mklv(self, args=''):
        return 'mklv %s' % args

    def rmdev(self, args=''):
        return 'rmdev %s' % args

    def rmvdev(self, args=''):
        return 'rmvdev %s' % args

    def lsmap(self, args=''):
        return 'lsmap %s' % args

    def lsdev(self, args=''):
        return 'lsdev %s' % args

    def rmsyscfg(self, args=''):
        return 'rmsyscfg %s' % args

    def chsysstate(self, args=''):
        return 'chsysstate %s' % args

    def mksyscfg(self, args=''):
        return 'mksyscfg %s' % args

    def lssyscfg(self, args=''):
        return 'lssyscfg %s' % args

    def cfgdev(self, args=''):
        return 'cfgdev %s' % args

    def mkvdev(self, args=''):
        return 'mkvdev %s' % args

    def lshwres(self, args=''):
        return 'lshwres %s' % args

    def hostname(self, args=''):
        return 'hostname %s' % args

    def vhost_by_instance_id(self, instance_id_hex):
        pass


class IVMCommand(BaseCommand):

    def lsvg(self, args=''):
        return 'ioscli ' + BaseCommand.lsvg(self, args)

    def mklv(self, args=''):
        return 'ioscli ' + BaseCommand.mklv(self, args)

    def rmdev(self, args=''):
        return 'ioscli ' + BaseCommand.rmdev(self, args)

    def rmvdev(self, args=''):
        return 'ioscli ' + BaseCommand.rmvdev(self, args=args)

    def lsmap(self, args=''):
        return 'ioscli ' + BaseCommand.lsmap(self, args)

    def lsdev(self, args=''):
        return 'ioscli ' + BaseCommand.lsdev(self, args)

    def cfgdev(self, args=''):
        return 'ioscli ' + BaseCommand.cfgdev(self, args=args)

    def mkvdev(self, args=''):
        return 'ioscli ' + BaseCommand.mkvdev(self, args=args)

    def hostname(self, args=''):
        return 'ioscli ' + BaseCommand.hostname(self, args=args)
