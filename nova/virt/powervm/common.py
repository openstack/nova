# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

import contextlib
import ftplib
import os
import uuid

import paramiko

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.virt.powervm import constants
from nova.virt.powervm import exception

LOG = logging.getLogger(__name__)


class Connection(object):

    def __init__(self, host, username, password, port=22, keyfile=None):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.keyfile = keyfile


def ssh_connect(connection):
    """Method to connect to remote system using ssh protocol.

    :param connection: a Connection object.
    :returns: paramiko.SSHClient -- an active ssh connection.
    :raises: PowerVMConnectionFailed
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(connection.host,
                    username=connection.username,
                    password=connection.password,
                    port=connection.port,
                    key_filename=connection.keyfile,
                    timeout=constants.POWERVM_CONNECTION_TIMEOUT)

        LOG.debug("SSH connection with %s established successfully." %
                  connection.host)

        # send TCP keepalive packets every 20 seconds
        ssh.get_transport().set_keepalive(20)

        return ssh
    except Exception:
        LOG.exception(_('Connection error connecting PowerVM manager'))
        raise exception.PowerVMConnectionFailed()


def check_connection(ssh, connection):
    """
    Checks the SSH connection to see if the transport is valid.
    If the connection is dead, a new connection is created and returned.

    :param ssh: an existing paramiko.SSHClient connection.
    :param connection: a Connection object.
    :returns: paramiko.SSHClient -- an active ssh connection.
    :raises: PowerVMConnectionFailed -- if the ssh connection fails.
    """
    # if the ssh client is not set or the transport is dead, re-connect
    if (ssh is None or
        ssh.get_transport() is None or
            not ssh.get_transport().is_active()):
            LOG.debug("Connection to host %s will be established." %
                      connection.host)
            ssh = ssh_connect(connection)

    return ssh


def ssh_command_as_root(ssh_connection, cmd, check_exit_code=True):
    """Method to execute remote command as root.

    :param connection: an active paramiko.SSHClient connection.
    :param command: string containing the command to run.
    :returns: Tuple -- a tuple of (stdout, stderr)
    :raises: processutils.ProcessExecutionError
    """
    LOG.debug(_('Running cmd (SSH-as-root): %s') % cmd)
    chan = ssh_connection._transport.open_session()
    # This command is required to be executed
    # in order to become root.
    chan.exec_command('ioscli oem_setup_env')
    bufsize = -1
    stdin = chan.makefile('wb', bufsize)
    stdout = chan.makefile('rb', bufsize)
    stderr = chan.makefile_stderr('rb', bufsize)
    # We run the command and then call 'exit' to exit from
    # super user environment.
    stdin.write('%s\n%s\n' % (cmd, 'exit'))
    stdin.flush()
    exit_status = chan.recv_exit_status()

    # Lets handle the error just like processutils.ssh_execute does.
    if exit_status != -1:
        LOG.debug(_('Result was %s') % exit_status)
        if check_exit_code and exit_status != 0:
            # TODO(mikal): I know this is weird, but it needs to be consistent
            # with processutils.execute. I will move this method to oslo in
            # a later commit.
            raise processutils.ProcessExecutionError(exit_code=exit_status,
                                                     stdout=stdout,
                                                     stderr=stderr,
                                                     cmd=''.join(cmd))

    return (stdout, stderr)


def ftp_put_command(connection, local_path, remote_dir):
    """Method to transfer a file via ftp.

    :param connection: a Connection object.
    :param local_path: path to the local file
    :param remote_dir: path to remote destination
    :raises: PowerVMFileTransferFailed
    """
    try:
        ftp = ftplib.FTP(host=connection.host,
                         user=connection.username,
                         passwd=connection.password)
        ftp.cwd(remote_dir)
        name = os.path.split(local_path)[1]
        f = open(local_path, "rb")
        ftp.storbinary("STOR " + name, f)
        f.close()
        ftp.close()
    except Exception:
        LOG.error(_('File transfer to PowerVM manager failed'))
        raise exception.PowerVMFTPTransferFailed(ftp_cmd='PUT',
                source_path=local_path, dest_path=remote_dir)


def ftp_get_command(connection, remote_path, local_path):
    """Retrieve a file via FTP

    :param connection: a Connection object.
    :param remote_path: path to the remote file
    :param local_path: path to local destination
    :raises: PowerVMFileTransferFailed
    """
    try:
        ftp = ftplib.FTP(host=connection.host,
                         user=connection.username,
                         passwd=connection.password)
        ftp.cwd(os.path.dirname(remote_path))
        name = os.path.basename(remote_path)
        LOG.debug(_("ftp GET %(remote_path)s to: %(local_path)s"),
                  {'remote_path': remote_path, 'local_path': local_path})
        with open(local_path, 'w') as ftpfile:
            ftpcmd = 'RETR %s' % name
            ftp.retrbinary(ftpcmd, ftpfile.write)
        ftp.close()
    except Exception:
        LOG.error(_("File transfer from PowerVM manager failed"))
        raise exception.PowerVMFTPTransferFailed(ftp_cmd='GET',
                source_path=remote_path, dest_path=local_path)


def aix_path_join(path_one, path_two):
    """Ensures file path is built correctly for remote UNIX system

    :param path_one: string of the first file path
    :param path_two: string of the second file path
    :returns: a uniform path constructed from both strings
    """
    if path_one.endswith('/'):
        path_one = path_one.rstrip('/')

    if path_two.startswith('/'):
        path_two = path_two.lstrip('/')

    final_path = path_one + '/' + path_two
    return final_path


@contextlib.contextmanager
def vios_to_vios_auth(source, dest, conn_info):
    """Context allowing for SSH between VIOS partitions

    This context will build an SSH key on the source host, put the key
    into the authorized_keys on the destination host, and make the
    private key file name available within the context.
    The key files and key inserted into authorized_keys will be
    removed when the context exits.

    :param source: source IP or DNS name
    :param dest: destination IP or DNS name
    :param conn_info: dictionary object with SSH connection
                      information for both hosts
    """
    KEY_BASE_NAME = "os-%s" % uuid.uuid4().hex
    keypair_uuid = uuid.uuid4()
    src_conn_obj = ssh_connect(conn_info)

    dest_conn_info = Connection(dest, conn_info.username,
                                       conn_info.password)
    dest_conn_obj = ssh_connect(dest_conn_info)

    def run_command(conn_obj, cmd):
        stdout, stderr = processutils.ssh_execute(conn_obj, cmd)
        return stdout.strip().splitlines()

    def build_keypair_on_source():
        mkkey = ('ssh-keygen -f %s -N "" -C %s' %
                    (KEY_BASE_NAME, keypair_uuid.hex))
        ssh_command_as_root(src_conn_obj, mkkey)

        chown_key = ('chown %s %s*' % (conn_info.username, KEY_BASE_NAME))
        ssh_command_as_root(src_conn_obj, chown_key)

        cat_key = ('cat %s.pub' % KEY_BASE_NAME)
        pubkey = run_command(src_conn_obj, cat_key)

        return pubkey[0]

    def cleanup_key_on_source():
        rmkey = 'rm %s*' % KEY_BASE_NAME
        run_command(src_conn_obj, rmkey)

    def insert_into_authorized_keys(public_key):
        echo_key = 'echo "%s" >> .ssh/authorized_keys' % public_key
        ssh_command_as_root(dest_conn_obj, echo_key)

    def remove_from_authorized_keys():
        rmkey = ('sed /%s/d .ssh/authorized_keys > .ssh/authorized_keys' %
                 keypair_uuid.hex)
        ssh_command_as_root(dest_conn_obj, rmkey)

    public_key = build_keypair_on_source()
    insert_into_authorized_keys(public_key)

    try:
        yield KEY_BASE_NAME
    finally:
        remove_from_authorized_keys()
        cleanup_key_on_source()
