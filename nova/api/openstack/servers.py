# Copyright 2010 OpenStack LLC.
# Copyright 2011 Piston Cloud Computing, Inc
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

import base64
import os
import traceback

from novaclient import exceptions as novaclient_exceptions
from lxml import etree
from webob import exc
import webob
from xml.dom import minidom

from nova import compute
from nova import network
from nova import db
from nova import exception
from nova import flags
from nova import image
from nova import log as logging
from nova import utils
from nova import quota
from nova.api.openstack import common
from nova.api.openstack import ips
from nova.api.openstack import wsgi
from nova.compute import instance_types
from nova.scheduler import api as scheduler_api
import nova.api.openstack
import nova.api.openstack.views.addresses
import nova.api.openstack.views.flavors
import nova.api.openstack.views.images
import nova.api.openstack.views.servers
from nova.api.openstack import xmlutil
from nova.rpc import common as rpc_common


LOG = logging.getLogger('nova.api.openstack.servers')
FLAGS = flags.FLAGS


class ConvertedException(exc.WSGIHTTPException):
    def __init__(self, code, title, explanation):
        self.code = code
        self.title = title
        self.explanation = explanation
        super(ConvertedException, self).__init__()


def novaclient_exception_converter(f):
    """Convert novaclient ClientException HTTP codes to webob exceptions.
    Has to be the outer-most decorator.
    """
    def new_f(*args, **kwargs):
        try:
            ret = f(*args, **kwargs)
            return ret
        except novaclient_exceptions.ClientException, e:
            raise ConvertedException(e.code, e.message, e.details)
    return new_f


class Controller(object):
    """ The Server API base controller class for the OpenStack API """

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()

    def index(self, req):
        """ Returns a list of server names and ids for a given user """
        try:
            servers = self._get_servers(req, is_detail=False)
        except exception.Invalid as err:
            return exc.HTTPBadRequest(explanation=str(err))
        except exception.NotFound:
            return exc.HTTPNotFound()
        return servers

    def detail(self, req):
        """ Returns a list of server details for a given user """
        try:
            servers = self._get_servers(req, is_detail=True)
        except exception.Invalid as err:
            return exc.HTTPBadRequest(explanation=str(err))
        except exception.NotFound as err:
            return exc.HTTPNotFound()
        return servers

    def _build_view(self, req, instance, is_detail=False):
        raise NotImplementedError()

    def _build_list(self, req, instances, is_detail=False):
        raise NotImplementedError()

    def _limit_items(self, items, req):
        raise NotImplementedError()

    def _action_rebuild(self, info, request, instance_id):
        raise NotImplementedError()

    def _get_block_device_mapping(self, data):
        """Get block_device_mapping from 'server' dictionary.
        Overidden by volumes controller.
        """
        return None

    def _get_networks_for_instance(self, req, instance):
        return ips._get_networks_for_instance(req.environ['nova.context'],
                                              self.network_api,
                                              instance)

    def _get_block_device_mapping(self, data):
        """Get block_device_mapping from 'server' dictionary.
        Overidden by volumes controller.
        """
        return None

    def _get_servers(self, req, is_detail):
        """Returns a list of servers, taking into account any search
        options specified.
        """

        search_opts = {}
        search_opts.update(req.str_GET)

        context = req.environ['nova.context']
        remove_invalid_options(context, search_opts,
                self._get_server_search_options())

        # Convert recurse_zones into a boolean
        search_opts['recurse_zones'] = utils.bool_from_str(
                search_opts.get('recurse_zones', False))

        # If search by 'status', we need to convert it to 'vm_state'
        # to pass on to child zones.
        if 'status' in search_opts:
            status = search_opts['status']
            state = common.vm_state_from_status(status)
            if state is None:
                reason = _('Invalid server status: %(status)s') % locals()
                raise exception.InvalidInput(reason=reason)
            search_opts['vm_state'] = state

        if 'changes-since' in search_opts:
            try:
                parsed = utils.parse_isotime(search_opts['changes-since'])
            except ValueError:
                msg = _('Invalid changes-since value')
                raise exc.HTTPBadRequest(explanation=msg)
            search_opts['changes-since'] = parsed

        # By default, compute's get_all() will return deleted instances.
        # If an admin hasn't specified a 'deleted' search option, we need
        # to filter out deleted instances by setting the filter ourselves.
        # ... Unless 'changes-since' is specified, because 'changes-since'
        # should return recently deleted images according to the API spec.

        if 'deleted' not in search_opts:
            if 'changes-since' not in search_opts:
                # No 'changes-since', so we only want non-deleted servers
                search_opts['deleted'] = False

        instance_list = self.compute_api.get_all(context,
                                                 search_opts=search_opts)

        limited_list = self._limit_items(instance_list, req)
        return self._build_list(req, limited_list, is_detail=is_detail)

    def _handle_quota_error(self, error):
        """
        Reraise quota errors as api-specific http exceptions
        """

        code_mappings = {
            "OnsetFileLimitExceeded":
                    _("Personality file limit exceeded"),
            "OnsetFilePathLimitExceeded":
                    _("Personality file path too long"),
            "OnsetFileContentLimitExceeded":
                    _("Personality file content too long"),
            "InstanceLimitExceeded":
                    _("Instance quotas have been exceeded")}

        expl = code_mappings.get(error.code)
        if expl:
            raise exc.HTTPRequestEntityTooLarge(explanation=expl,
                                                headers={'Retry-After': 0})
        # if the original error is okay, just reraise it
        raise error

    def _deserialize_create(self, request):
        """
        Deserialize a create request

        Overrides normal behavior in the case of xml content
        """
        if request.content_type == "application/xml":
            deserializer = ServerXMLDeserializer()
            return deserializer.deserialize(request.body)
        else:
            return self._deserialize(request.body, request.get_content_type())

    def _validate_server_name(self, value):
        if not isinstance(value, basestring):
            msg = _("Server name is not a string or unicode")
            raise exc.HTTPBadRequest(explanation=msg)

        if value.strip() == '':
            msg = _("Server name is an empty string")
            raise exc.HTTPBadRequest(explanation=msg)

    def _get_kernel_ramdisk_from_image(self, req, image_service, image_id):
        """Fetch an image from the ImageService, then if present, return the
        associated kernel and ramdisk image IDs.
        """
        context = req.environ['nova.context']
        image_meta = image_service.show(context, image_id)
        # NOTE(sirp): extracted to a separate method to aid unit-testing, the
        # new method doesn't need a request obj or an ImageService stub
        kernel_id, ramdisk_id = self._do_get_kernel_ramdisk_from_image(
            image_meta)
        return kernel_id, ramdisk_id

    @staticmethod
    def  _do_get_kernel_ramdisk_from_image(image_meta):
        """Given an ImageService image_meta, return kernel and ramdisk image
        ids if present.

        This is only valid for `ami` style images.
        """
        image_id = image_meta['id']
        if image_meta['status'] != 'active':
            raise exception.ImageUnacceptable(image_id=image_id,
                                              reason=_("status is not active"))

        if image_meta.get('container_format') != 'ami':
            return None, None

        try:
            kernel_id = image_meta['properties']['kernel_id']
        except KeyError:
            raise exception.KernelNotFoundForImage(image_id=image_id)

        try:
            ramdisk_id = image_meta['properties']['ramdisk_id']
        except KeyError:
            ramdisk_id = None

        return kernel_id, ramdisk_id

    def _get_injected_files(self, personality):
        """
        Create a list of injected files from the personality attribute

        At this time, injected_files must be formatted as a list of
        (file_path, file_content) pairs for compatibility with the
        underlying compute service.
        """
        injected_files = []

        for item in personality:
            try:
                path = item['path']
                contents = item['contents']
            except KeyError as key:
                expl = _('Bad personality format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad personality format')
                raise exc.HTTPBadRequest(explanation=expl)
            try:
                contents = base64.b64decode(contents)
            except TypeError:
                expl = _('Personality content for %s cannot be decoded') % path
                raise exc.HTTPBadRequest(explanation=expl)
            injected_files.append((path, contents))
        return injected_files

    def _get_server_admin_password_old_style(self, server):
        """ Determine the admin password for a server on creation """
        return utils.generate_password(FLAGS.password_length)

    def _get_server_admin_password_new_style(self, server):
        """ Determine the admin password for a server on creation """
        password = server.get('adminPass')

        if password is None:
            return utils.generate_password(FLAGS.password_length)
        if not isinstance(password, basestring) or password == '':
            msg = _("Invalid adminPass")
            raise exc.HTTPBadRequest(explanation=msg)
        return password

    def _get_requested_networks(self, requested_networks):
        """
        Create a list of requested networks from the networks attribute
        """
        networks = []
        for network in requested_networks:
            try:
                network_uuid = network['uuid']

                if not utils.is_uuid_like(network_uuid):
                    msg = _("Bad networks format: network uuid is not in"
                         " proper format (%s)") % network_uuid
                    raise exc.HTTPBadRequest(explanation=msg)

                #fixed IP address is optional
                #if the fixed IP address is not provided then
                #it will use one of the available IP address from the network
                address = network.get('fixed_ip', None)
                if address is not None and not utils.is_valid_ipv4(address):
                    msg = _("Invalid fixed IP address (%s)") % address
                    raise exc.HTTPBadRequest(explanation=msg)
                # check if the network id is already present in the list,
                # we don't want duplicate networks to be passed
                # at the boot time
                for id, ip in networks:
                    if id == network_uuid:
                        expl = _("Duplicate networks (%s) are not allowed")\
                                % network_uuid
                        raise exc.HTTPBadRequest(explanation=expl)

                networks.append((network_uuid, address))
            except KeyError as key:
                expl = _('Bad network format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad networks format')
                raise exc.HTTPBadRequest(explanation=expl)

        return networks

    def _validate_user_data(self, user_data):
        """Check if the user_data is encoded properly"""
        if not user_data:
            return
        try:
            user_data = base64.b64decode(user_data)
        except TypeError:
            expl = _('Userdata content cannot be decoded')
            raise exc.HTTPBadRequest(explanation=expl)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def show(self, req, id):
        """ Returns server details by server id """
        try:
            instance = self.compute_api.routing_get(
                req.environ['nova.context'], id)
            return self._build_view(req, instance, is_detail=True)
        except exception.NotFound:
            raise exc.HTTPNotFound()

    def _get_key_name(self, req, body):
        """ Get default keypair if not set """
        raise NotImplementedError()

    def create(self, req, body):
        """ Creates a new server for a given user """

        if not body:
            raise exc.HTTPUnprocessableEntity()

        if not 'server' in body:
            raise exc.HTTPUnprocessableEntity()

        body['server']['key_name'] = self._get_key_name(req, body)

        context = req.environ['nova.context']
        server_dict = body['server']
        password = self._get_server_admin_password(server_dict)

        if not 'name' in server_dict:
            msg = _("Server name is not defined")
            raise exc.HTTPBadRequest(explanation=msg)

        name = server_dict['name']
        self._validate_server_name(name)
        name = name.strip()

        image_href = self._image_ref_from_req_data(body)
        # If the image href was generated by nova api, strip image_href
        # down to an id and use the default glance connection params

        if str(image_href).startswith(req.application_url):
            image_href = image_href.split('/').pop()
        try:
            image_service, image_id = image.get_image_service(context,
                    image_href)
            kernel_id, ramdisk_id = self._get_kernel_ramdisk_from_image(
                    req, image_service, image_id)
            images = set([str(x['id']) for x in image_service.index(context)])
            assert str(image_id) in images
        except Exception, e:
            msg = _("Cannot find requested image %(image_href)s: %(e)s" %
                                                                    locals())
            raise exc.HTTPBadRequest(explanation=msg)

        personality = server_dict.get('personality')
        config_drive = server_dict.get('config_drive')

        injected_files = []
        if personality:
            injected_files = self._get_injected_files(personality)

        sg_names = []
        security_groups = server_dict.get('security_groups')
        if security_groups is not None:
            sg_names = [sg['name'] for sg in security_groups if sg.get('name')]
        if not sg_names:
            sg_names.append('default')

        sg_names = list(set(sg_names))

        requested_networks = server_dict.get('networks')
        if requested_networks is not None:
            requested_networks = self._get_requested_networks(
                                                    requested_networks)

        try:
            flavor_id = self._flavor_id_from_req_data(body)
        except ValueError as error:
            msg = _("Invalid flavorRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        zone_blob = server_dict.get('blob')

        # optional openstack extensions:
        key_name = server_dict.get('key_name')
        user_data = server_dict.get('user_data')
        self._validate_user_data(user_data)

        availability_zone = server_dict.get('availability_zone')
        name = server_dict['name']
        self._validate_server_name(name)
        name = name.strip()

        block_device_mapping = self._get_block_device_mapping(server_dict)

        # Only allow admins to specify their own reservation_ids
        # This is really meant to allow zones to work.
        reservation_id = server_dict.get('reservation_id')
        if all([reservation_id is not None,
                reservation_id != '',
                not context.is_admin]):
            reservation_id = None

        ret_resv_id = server_dict.get('return_reservation_id', False)

        min_count = server_dict.get('min_count')
        max_count = server_dict.get('max_count')
        # min_count and max_count are optional.  If they exist, they come
        # in as strings.  We want to default 'min_count' to 1, and default
        # 'max_count' to be 'min_count'.
        min_count = int(min_count) if min_count else 1
        max_count = int(max_count) if max_count else min_count
        if min_count > max_count:
            min_count = max_count

        try:
            inst_type = \
                    instance_types.get_instance_type_by_flavor_id(flavor_id)

            (instances, resv_id) = self.compute_api.create(context,
                            inst_type,
                            image_id,
                            kernel_id=kernel_id,
                            ramdisk_id=ramdisk_id,
                            display_name=name,
                            display_description=name,
                            key_name=key_name,
                            metadata=server_dict.get('metadata', {}),
                            access_ip_v4=server_dict.get('accessIPv4'),
                            access_ip_v6=server_dict.get('accessIPv6'),
                            injected_files=injected_files,
                            admin_password=password,
                            zone_blob=zone_blob,
                            reservation_id=reservation_id,
                            min_count=min_count,
                            max_count=max_count,
                            requested_networks=requested_networks,
                            security_group=sg_names,
                            user_data=user_data,
                            availability_zone=availability_zone,
                            config_drive=config_drive,
                            block_device_mapping=block_device_mapping,
                            wait_for_instances=not ret_resv_id)
        except quota.QuotaError as error:
            self._handle_quota_error(error)
        except exception.InstanceTypeMemoryTooSmall as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.InstanceTypeDiskTooSmall as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except exception.ImageNotFound as error:
            msg = _("Can not find requested image")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.FlavorNotFound as error:
            msg = _("Invalid flavorRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.KeypairNotFound as error:
            msg = _("Invalid key_name provided.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.SecurityGroupNotFound as error:
            raise exc.HTTPBadRequest(explanation=unicode(error))
        except rpc_common.RemoteError as err:
            msg = "%(err_type)s: %(err_msg)s" % \
                  {'err_type': err.exc_type, 'err_msg': err.value}
            raise exc.HTTPBadRequest(explanation=msg)
        # Let the caller deal with unhandled exceptions.

        # If the caller wanted a reservation_id, return it
        if ret_resv_id:
            return {'reservation_id': resv_id}

        # Instances is a list
        instance = instances[0]
        if not instance.get('_is_precooked', False):
            instance['instance_type'] = inst_type
            instance['image_ref'] = image_href

        server = self._build_view(req, instance, is_detail=True)
        if '_is_precooked' in server['server']:
            del server['server']['_is_precooked']
        else:
            server['server']['adminPass'] = password
        return server

    def _delete(self, context, id):
        if FLAGS.reclaim_instance_interval:
            self.compute_api.soft_delete(context, id)
        else:
            self.compute_api.delete(context, id)

    @scheduler_api.redirect_handler
    def update(self, req, id, body):
        """Update server then pass on to version-specific controller"""
        if len(req.body) == 0:
            raise exc.HTTPUnprocessableEntity()

        if not body:
            raise exc.HTTPUnprocessableEntity()

        ctxt = req.environ['nova.context']
        update_dict = {}

        if 'name' in body['server']:
            name = body['server']['name']
            self._validate_server_name(name)
            update_dict['display_name'] = name.strip()

        if 'accessIPv4' in body['server']:
            access_ipv4 = body['server']['accessIPv4']
            update_dict['access_ip_v4'] = access_ipv4.strip()

        if 'accessIPv6' in body['server']:
            access_ipv6 = body['server']['accessIPv6']
            update_dict['access_ip_v6'] = access_ipv6.strip()

        try:
            self.compute_api.update(ctxt, id, **update_dict)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return self._update(ctxt, req, id, body)

    def _update(self, context, req, id, inst_dict):
        return exc.HTTPNotImplemented()

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def action(self, req, id, body):
        """Multi-purpose method used to take actions on a server"""

        self.actions = {
            'changePassword': self._action_change_password,
            'reboot': self._action_reboot,
            'resize': self._action_resize,
            'confirmResize': self._action_confirm_resize,
            'revertResize': self._action_revert_resize,
            'rebuild': self._action_rebuild,
            'createImage': self._action_create_image,
        }

        if FLAGS.allow_admin_api:
            admin_actions = {
                'createBackup': self._action_create_backup,
            }
            self.actions.update(admin_actions)

        for key in body:
            if key in self.actions:
                return self.actions[key](body, req, id)
            else:
                msg = _("There is no such server action: %s") % (key,)
                raise exc.HTTPBadRequest(explanation=msg)

        msg = _("Invalid request body")
        raise exc.HTTPBadRequest(explanation=msg)

    def _action_create_backup(self, input_dict, req, instance_id):
        """Backup a server instance.

        Images now have an `image_type` associated with them, which can be
        'snapshot' or the backup type, like 'daily' or 'weekly'.

        If the image_type is backup-like, then the rotation factor can be
        included and that will cause the oldest backups that exceed the
        rotation factor to be deleted.

        """
        entity = input_dict["createBackup"]

        try:
            image_name = entity["name"]
            backup_type = entity["backup_type"]
            rotation = entity["rotation"]

        except KeyError as missing_key:
            msg = _("createBackup entity requires %s attribute") % missing_key
            raise exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed createBackup entity")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            rotation = int(rotation)
        except ValueError:
            msg = _("createBackup attribute 'rotation' must be an integer")
            raise exc.HTTPBadRequest(explanation=msg)

        # preserve link to server in image properties
        server_ref = os.path.join(req.application_url,
                                  'servers',
                                  str(instance_id))
        props = {'instance_ref': server_ref}

        metadata = entity.get('metadata', {})
        context = req.environ["nova.context"]
        common.check_img_metadata_quota_limit(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise exc.HTTPBadRequest(explanation=msg)

        image = self.compute_api.backup(context,
                                        instance_id,
                                        image_name,
                                        backup_type,
                                        rotation,
                                        extra_properties=props)

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = os.path.join(req.application_url, 'images', image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    @common.check_snapshots_enabled
    def _action_create_image(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_change_password(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_confirm_resize(self, input_dict, req, id):
        try:
            self.compute_api.confirm_resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in confirm-resize %s"), e)
            raise exc.HTTPBadRequest()
        return exc.HTTPNoContent()

    def _action_revert_resize(self, input_dict, req, id):
        try:
            self.compute_api.revert_resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in revert-resize %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    def _action_resize(self, input_dict, req, id):
        return exc.HTTPNotImplemented()

    def _action_reboot(self, input_dict, req, id):
        if 'reboot' in input_dict and 'type' in input_dict['reboot']:
            valid_reboot_types = ['HARD', 'SOFT']
            reboot_type = input_dict['reboot']['type'].upper()
            if not valid_reboot_types.count(reboot_type):
                msg = _("Argument 'type' for reboot is not HARD or SOFT")
                LOG.exception(msg)
                raise exc.HTTPBadRequest(explanation=msg)
        else:
            msg = _("Missing argument 'type' for reboot")
            LOG.exception(msg)
            raise exc.HTTPBadRequest(explanation=msg)
        try:
            self.compute_api.reboot(req.environ['nova.context'], id,
                    reboot_type)
        except Exception, e:
            LOG.exception(_("Error in reboot %s"), e)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def lock(self, req, id):
        """
        lock the instance with id
        admin only operation

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.lock(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def unlock(self, req, id):
        """
        unlock the instance with id
        admin only operation

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.unlock(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unlock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def get_lock(self, req, id):
        """
        return the boolean state of (instance with id)'s lock

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.get_lock(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::get_lock %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def reset_network(self, req, id):
        """
        Reset networking on an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.reset_network(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::reset_network %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def inject_network_info(self, req, id):
        """
        Inject network info for an instance (admin only).

        """
        context = req.environ['nova.context']
        try:
            self.compute_api.inject_network_info(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::inject_network_info %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def pause(self, req, id):
        """ Permit Admins to Pause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.pause(ctxt, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::pause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def unpause(self, req, id):
        """ Permit Admins to Unpause the server. """
        ctxt = req.environ['nova.context']
        try:
            self.compute_api.unpause(ctxt, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("Compute.api::unpause %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def suspend(self, req, id):
        """permit admins to suspend the server"""
        context = req.environ['nova.context']
        try:
            self.compute_api.suspend(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::suspend %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def resume(self, req, id):
        """permit admins to resume the server from suspend"""
        context = req.environ['nova.context']
        try:
            self.compute_api.resume(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::resume %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def migrate(self, req, id):
        try:
            self.compute_api.resize(req.environ['nova.context'], id)
        except Exception, e:
            LOG.exception(_("Error in migrate %s"), e)
            raise exc.HTTPBadRequest()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def rescue(self, req, id, body={}):
        """Permit users to rescue the server."""
        context = req.environ["nova.context"]
        try:
            if 'rescue' in body and body['rescue'] and \
                    'adminPass' in body['rescue']:
                password = body['rescue']['adminPass']
            else:
                password = utils.generate_password(FLAGS.password_length)
            self.compute_api.rescue(context, id, rescue_password=password)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::rescue %s"), readable)
            raise exc.HTTPUnprocessableEntity()

        return {'adminPass': password}

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def unrescue(self, req, id):
        """Permit users to unrescue the server."""
        context = req.environ["nova.context"]
        try:
            self.compute_api.unrescue(context, id)
        except Exception:
            readable = traceback.format_exc()
            LOG.exception(_("compute.api::unrescue %s"), readable)
            raise exc.HTTPUnprocessableEntity()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def get_ajax_console(self, req, id):
        """Returns a url to an instance's ajaxterm console."""
        try:
            self.compute_api.get_ajax_console(req.environ['nova.context'],
                int(id))
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def get_vnc_console(self, req, id):
        """Returns a url to an instance's ajaxterm console."""
        try:
            self.compute_api.get_vnc_console(req.environ['nova.context'],
                                             int(id))
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def diagnostics(self, req, id):
        """Permit Admins to retrieve server diagnostics."""
        ctxt = req.environ["nova.context"]
        return self.compute_api.get_diagnostics(ctxt, id)

    def actions(self, req, id):
        """Permit Admins to retrieve server actions."""
        ctxt = req.environ["nova.context"]
        items = self.compute_api.get_actions(ctxt, id)
        actions = []
        # TODO(jk0): Do not do pre-serialization here once the default
        # serializer is updated
        for item in items:
            actions.append(dict(
                created_at=str(item.created_at),
                action=item.action,
                error=item.error))
        return dict(actions=actions)

    def resize(self, req, instance_id, flavor_id):
        """Begin the resize process with given instance/flavor."""
        context = req.environ["nova.context"]

        try:
            self.compute_api.resize(context, instance_id, flavor_id)
        except exception.FlavorNotFound:
            msg = _("Unable to locate requested flavor.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSameSize:
            msg = _("Resize requires a change in size.")
            raise exc.HTTPBadRequest(explanation=msg)
        except exception.CannotResizeToSmallerSize:
            msg = _("Resizing to a smaller size is not supported.")
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)


class ControllerV10(Controller):
    """v1.0 OpenStack API controller"""

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self._delete(req.environ['nova.context'], id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    def _get_key_name(self, req, body):
        context = req.environ["nova.context"]
        keypairs = db.key_pair_get_all_by_user(context,
                                               context.user_id)
        if keypairs:
            return keypairs[0]['name']

    def _image_ref_from_req_data(self, data):
        return data['server']['imageId']

    def _flavor_id_from_req_data(self, data):
        return data['server']['flavorId']

    def _build_view(self, req, instance, is_detail=False):
        addresses = nova.api.openstack.views.addresses.ViewBuilderV10()
        builder = nova.api.openstack.views.servers.ViewBuilderV10(addresses)
        networks = self._get_networks_for_instance(req, instance)
        return builder.build(instance, networks, is_detail=is_detail)

    def _build_list(self, req, instances, is_detail=False):
        addresses = nova.api.openstack.views.addresses.ViewBuilderV10()
        builder = nova.api.openstack.views.servers.ViewBuilderV10(addresses)
        get_nw = self._get_networks_for_instance
        inst_data = [(inst, get_nw(req, inst)) for inst in instances]
        return builder.build_list(inst_data, is_detail=is_detail)

    def _limit_items(self, items, req):
        return common.limited(items, req)

    def _update(self, context, req, id, inst_dict):
        if 'adminPass' in inst_dict['server']:
            self.compute_api.set_admin_password(context, id,
                    inst_dict['server']['adminPass'])
        return exc.HTTPNoContent()

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        try:
            flavor_id = input_dict["resize"]["flavorId"]
        except (KeyError, TypeError):
            msg = _("Resize requests require 'flavorId' attribute.")
            raise exc.HTTPBadRequest(explanation=msg)

        return self.resize(req, id, flavor_id)

    def _action_rebuild(self, info, request, instance_id):
        context = request.environ['nova.context']

        try:
            image_id = info["rebuild"]["imageId"]
        except (KeyError, TypeError):
            msg = _("Could not parse imageId from request.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        password = utils.generate_password(FLAGS.password_length)

        try:
            self.compute_api.rebuild(context, instance_id, image_id, password)
        except exception.RebuildRequiresActiveInstance:
            msg = _("Instance %s must be active to rebuild.") % instance_id
            raise exc.HTTPConflict(explanation=msg)

        return webob.Response(status_int=202)

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self._get_server_admin_password_old_style(server)

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin"""
        return 'reservation_id', 'fixed_ip', 'name', 'recurse_zones'


class ControllerV11(Controller):
    """v1.1 OpenStack API controller"""

    @novaclient_exception_converter
    @scheduler_api.redirect_handler
    def delete(self, req, id):
        """ Destroys a server """
        try:
            self._delete(req.environ['nova.context'], id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

    def _get_key_name(self, req, body):
        if 'server' in body:
            try:
                return body['server'].get('key_name')
            except AttributeError:
                msg = _("Malformed server entity")
                raise exc.HTTPBadRequest(explanation=msg)

    def _image_ref_from_req_data(self, data):
        try:
            return data['server']['imageRef']
        except (TypeError, KeyError):
            msg = _("Missing imageRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

    def _flavor_id_from_req_data(self, data):
        try:
            flavor_ref = data['server']['flavorRef']
        except (TypeError, KeyError):
            msg = _("Missing flavorRef attribute")
            raise exc.HTTPBadRequest(explanation=msg)

        return common.get_id_from_href(flavor_ref)

    def _build_view(self, req, instance, is_detail=False):
        project_id = getattr(req.environ['nova.context'], 'project_id', '')
        base_url = req.application_url
        flavor_builder = nova.api.openstack.views.flavors.ViewBuilderV11(
            base_url, project_id)
        image_builder = nova.api.openstack.views.images.ViewBuilderV11(
            base_url, project_id)
        addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV11()
        builder = nova.api.openstack.views.servers.ViewBuilderV11(
            addresses_builder, flavor_builder, image_builder,
            base_url, project_id)
        networks = self._get_networks_for_instance(req, instance)
        return builder.build(instance, networks, is_detail=is_detail)

    def _build_list(self, req, instances, is_detail=False):
        params = req.GET.copy()
        pagination_params = common.get_pagination_params(req)
        # Update params with int() values from pagination params
        for key, val in pagination_params.iteritems():
            params[key] = val

        project_id = getattr(req.environ['nova.context'], 'project_id', '')
        base_url = req.application_url
        flavor_builder = nova.api.openstack.views.flavors.ViewBuilderV11(
            base_url, project_id)
        image_builder = nova.api.openstack.views.images.ViewBuilderV11(
            base_url, project_id)
        addresses_builder = nova.api.openstack.views.addresses.ViewBuilderV11()
        builder = nova.api.openstack.views.servers.ViewBuilderV11(
            addresses_builder, flavor_builder, image_builder,
            base_url, project_id)
        get_nw = self._get_networks_for_instance
        inst_data = [(inst, get_nw(req, inst)) for inst in instances]
        return builder.build_list(inst_data, is_detail=is_detail, **params)

    def _action_change_password(self, input_dict, req, id):
        context = req.environ['nova.context']
        if (not 'changePassword' in input_dict
            or not 'adminPass' in input_dict['changePassword']):
            msg = _("No adminPass was specified")
            return exc.HTTPBadRequest(explanation=msg)
        password = input_dict['changePassword']['adminPass']
        if not isinstance(password, basestring) or password == '':
            msg = _("Invalid adminPass")
            return exc.HTTPBadRequest(explanation=msg)
        self.compute_api.set_admin_password(context, id, password)
        return webob.Response(status_int=202)

    def _limit_items(self, items, req):
        return common.limited_by_marker(items, req)

    def _validate_metadata(self, metadata):
        """Ensure that we can work with the metadata given."""
        try:
            metadata.iteritems()
        except AttributeError as ex:
            msg = _("Unable to parse metadata key/value pairs.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

    def _decode_personalities(self, personalities):
        """Decode the Base64-encoded personalities."""
        for personality in personalities:
            try:
                path = personality["path"]
                contents = personality["contents"]
            except (KeyError, TypeError):
                msg = _("Unable to parse personality path/contents.")
                LOG.info(msg)
                raise exc.HTTPBadRequest(explanation=msg)

            try:
                personality["contents"] = base64.b64decode(contents)
            except TypeError:
                msg = _("Personality content could not be Base64 decoded.")
                LOG.info(msg)
                raise exc.HTTPBadRequest(explanation=msg)

    def _update(self, context, req, id, inst_dict):
        instance = self.compute_api.routing_get(context, id)
        return self._build_view(req, instance, is_detail=True)

    def _action_resize(self, input_dict, req, id):
        """ Resizes a given instance to the flavor size requested """
        try:
            flavor_ref = input_dict["resize"]["flavorRef"]
            if not flavor_ref:
                msg = _("Resize request has invalid 'flavorRef' attribute.")
                raise exc.HTTPBadRequest(explanation=msg)
        except (KeyError, TypeError):
            msg = _("Resize requests require 'flavorRef' attribute.")
            raise exc.HTTPBadRequest(explanation=msg)

        return self.resize(req, id, flavor_ref)

    def _action_rebuild(self, info, request, instance_id):
        context = request.environ['nova.context']

        try:
            image_href = info["rebuild"]["imageRef"]
        except (KeyError, TypeError):
            msg = _("Could not parse imageRef from request.")
            LOG.debug(msg)
            raise exc.HTTPBadRequest(explanation=msg)

        personalities = info["rebuild"].get("personality", [])
        metadata = info["rebuild"].get("metadata")
        name = info["rebuild"].get("name")

        if metadata:
            self._validate_metadata(metadata)
        self._decode_personalities(personalities)

        if 'rebuild' in info and 'adminPass' in info['rebuild']:
            password = info['rebuild']['adminPass']
        else:
            password = utils.generate_password(FLAGS.password_length)

        try:
            self.compute_api.rebuild(context, instance_id, image_href,
                                     password, name=name, metadata=metadata,
                                     files_to_inject=personalities)
        except exception.RebuildRequiresActiveInstance:
            msg = _("Instance %s must be active to rebuild.") % instance_id
            raise exc.HTTPConflict(explanation=msg)
        except exception.InstanceNotFound:
            msg = _("Instance %s could not be found") % instance_id
            raise exc.HTTPNotFound(explanation=msg)

        instance = self.compute_api.routing_get(context, instance_id)
        view = self._build_view(request, instance, is_detail=True)
        view['server']['adminPass'] = password

        return view

    @common.check_snapshots_enabled
    def _action_create_image(self, input_dict, req, instance_id):
        """Snapshot a server instance."""
        entity = input_dict.get("createImage", {})

        try:
            image_name = entity["name"]

        except KeyError:
            msg = _("createImage entity requires name attribute")
            raise exc.HTTPBadRequest(explanation=msg)

        except TypeError:
            msg = _("Malformed createImage entity")
            raise exc.HTTPBadRequest(explanation=msg)

        # preserve link to server in image properties
        server_ref = os.path.join(req.application_url,
                                  'servers',
                                  str(instance_id))
        props = {'instance_ref': server_ref}

        metadata = entity.get('metadata', {})
        context = req.environ['nova.context']
        common.check_img_metadata_quota_limit(context, metadata)
        try:
            props.update(metadata)
        except ValueError:
            msg = _("Invalid metadata")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            image = self.compute_api.snapshot(context,
                                              instance_id,
                                              image_name,
                                              extra_properties=props)
        except exception.InstanceBusy:
            msg = _("Server is currently creating an image. Please wait.")
            raise webob.exc.HTTPConflict(explanation=msg)

        # build location of newly-created image entity
        image_id = str(image['id'])
        image_ref = os.path.join(req.application_url, 'images', image_id)

        resp = webob.Response(status_int=202)
        resp.headers['Location'] = image_ref
        return resp

    def get_default_xmlns(self, req):
        return common.XML_NS_V11

    def _get_server_admin_password(self, server):
        """ Determine the admin password for a server on creation """
        return self._get_server_admin_password_new_style(server)

    def _get_server_search_options(self):
        """Return server search options allowed by non-admin"""
        return ('reservation_id', 'name', 'recurse_zones',
                'status', 'image', 'flavor', 'changes-since')


class HeadersSerializer(wsgi.ResponseHeadersSerializer):

    def create(self, response, data):
        response.status_int = 202

    def delete(self, response, data):
        response.status_int = 204

    def action(self, response, data):
        response.status_int = 202


class ServerXMLSerializer(wsgi.XMLDictSerializer):

    NSMAP = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}

    def __init__(self):
        self.metadata_serializer = common.MetadataXMLSerializer()
        self.addresses_serializer = ips.IPXMLSerializer()

    def _create_metadata_node(self, metadata_dict):
        metadata_elem = etree.Element('metadata', nsmap=self.NSMAP)
        self.metadata_serializer.populate_metadata(metadata_elem,
                                                   metadata_dict)
        return metadata_elem

    def _create_image_node(self, image_dict):
        image_elem = etree.Element('image', nsmap=self.NSMAP)
        image_elem.set('id', str(image_dict['id']))
        for link in image_dict.get('links', []):
            elem = etree.SubElement(image_elem,
                                    '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])
        return image_elem

    def _create_flavor_node(self, flavor_dict):
        flavor_elem = etree.Element('flavor', nsmap=self.NSMAP)
        flavor_elem.set('id', str(flavor_dict['id']))
        for link in flavor_dict.get('links', []):
            elem = etree.SubElement(flavor_elem,
                                    '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])
        return flavor_elem

    def _create_addresses_node(self, addresses_dict):
        addresses_elem = etree.Element('addresses', nsmap=self.NSMAP)
        self.addresses_serializer.populate_addresses_node(addresses_elem,
                                                          addresses_dict)
        return addresses_elem

    def _populate_server(self, server_elem, server_dict, detailed=False):
        """Populate a server xml element from a dict."""

        server_elem.set('name', server_dict['name'])
        server_elem.set('id', str(server_dict['id']))
        if detailed:
            server_elem.set('uuid', str(server_dict['uuid']))
            server_elem.set('userId', str(server_dict['user_id']))
            server_elem.set('tenantId', str(server_dict['tenant_id']))
            server_elem.set('updated', str(server_dict['updated']))
            server_elem.set('created', str(server_dict['created']))
            server_elem.set('hostId', str(server_dict['hostId']))
            server_elem.set('accessIPv4', str(server_dict['accessIPv4']))
            server_elem.set('accessIPv6', str(server_dict['accessIPv6']))
            server_elem.set('status', str(server_dict['status']))
            if 'progress' in server_dict:
                server_elem.set('progress', str(server_dict['progress']))
            image_elem = self._create_image_node(server_dict['image'])
            server_elem.append(image_elem)

            flavor_elem = self._create_flavor_node(server_dict['flavor'])
            server_elem.append(flavor_elem)

            meta_elem = self._create_metadata_node(
                            server_dict.get('metadata', {}))
            server_elem.append(meta_elem)

            addresses_elem = self._create_addresses_node(
                            server_dict.get('addresses', {}))
            server_elem.append(addresses_elem)
            groups = server_dict.get('security_groups')
            if groups:
                groups_elem = etree.SubElement(server_elem, 'security_groups')
                for group in groups:
                    group_elem = etree.SubElement(groups_elem,
                                                  'security_group')
                    group_elem.set('name', group['name'])

        self._populate_links(server_elem, server_dict.get('links', []))

    def _populate_links(self, parent, links):
        for link in links:
            elem = etree.SubElement(parent,
                                    '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])

    def index(self, servers_dict):
        servers = etree.Element('servers', nsmap=self.NSMAP)
        for server_dict in servers_dict['servers']:
            server = etree.SubElement(servers, 'server')
            self._populate_server(server, server_dict, False)

        self._populate_links(servers, servers_dict.get('servers_links', []))
        return self._to_xml(servers)

    def detail(self, servers_dict):
        servers = etree.Element('servers', nsmap=self.NSMAP)
        for server_dict in servers_dict['servers']:
            server = etree.SubElement(servers, 'server')
            self._populate_server(server, server_dict, True)
        return self._to_xml(servers)

    def show(self, server_dict):
        server = etree.Element('server', nsmap=self.NSMAP)
        self._populate_server(server, server_dict['server'], True)
        return self._to_xml(server)

    def create(self, server_dict):
        server = etree.Element('server', nsmap=self.NSMAP)
        self._populate_server(server, server_dict['server'], True)
        server.set('adminPass', server_dict['server']['adminPass'])
        return self._to_xml(server)

    def action(self, server_dict):
        #NOTE(bcwaldon): We need a way to serialize actions individually. This
        # assumes all actions return a server entity
        return self.create(server_dict)

    def update(self, server_dict):
        server = etree.Element('server', nsmap=self.NSMAP)
        self._populate_server(server, server_dict['server'], True)
        return self._to_xml(server)


class ServerXMLDeserializer(wsgi.XMLDeserializer):
    """
    Deserializer to handle xml-formatted server create requests.

    Handles standard server attributes as well as optional metadata
    and personality attributes
    """

    metadata_deserializer = common.MetadataXMLDeserializer()

    def create(self, string):
        """Deserialize an xml-formatted server create request"""
        dom = minidom.parseString(string)
        server = self._extract_server(dom)
        return {'body': {'server': server}}

    def _extract_server(self, node):
        """Marshal the server attribute of a parsed request"""
        server = {}
        server_node = self.find_first_child_named(node, 'server')

        attributes = ["name", "imageId", "flavorId", "adminPass"]
        for attr in attributes:
            if server_node.getAttribute(attr):
                server[attr] = server_node.getAttribute(attr)

        metadata_node = self.find_first_child_named(server_node, "metadata")
        server["metadata"] = self.metadata_deserializer.extract_metadata(
                                                            metadata_node)

        server["personality"] = self._extract_personality(server_node)

        return server

    def _extract_personality(self, server_node):
        """Marshal the personality attribute of a parsed request"""
        node = self.find_first_child_named(server_node, "personality")
        personality = []
        if node is not None:
            for file_node in self.find_children_named(node, "file"):
                item = {}
                if file_node.hasAttribute("path"):
                    item["path"] = file_node.getAttribute("path")
                item["contents"] = self.extract_text(file_node)
                personality.append(item)
        return personality


class ServerXMLDeserializerV11(wsgi.MetadataXMLDeserializer):
    """
    Deserializer to handle xml-formatted server create requests.

    Handles standard server attributes as well as optional metadata
    and personality attributes
    """

    metadata_deserializer = common.MetadataXMLDeserializer()

    def action(self, string):
        dom = minidom.parseString(string)
        action_node = dom.childNodes[0]
        action_name = action_node.tagName

        action_deserializer = {
            'createImage': self._action_create_image,
            'createBackup': self._action_create_backup,
            'changePassword': self._action_change_password,
            'reboot': self._action_reboot,
            'rebuild': self._action_rebuild,
            'resize': self._action_resize,
            'confirmResize': self._action_confirm_resize,
            'revertResize': self._action_revert_resize,
        }.get(action_name, self.default)

        action_data = action_deserializer(action_node)

        return {'body': {action_name: action_data}}

    def _action_create_image(self, node):
        return self._deserialize_image_action(node, ('name',))

    def _action_create_backup(self, node):
        attributes = ('name', 'backup_type', 'rotation')
        return self._deserialize_image_action(node, attributes)

    def _action_change_password(self, node):
        if not node.hasAttribute("adminPass"):
            raise AttributeError("No adminPass was specified in request")
        return {"adminPass": node.getAttribute("adminPass")}

    def _action_reboot(self, node):
        if not node.hasAttribute("type"):
            raise AttributeError("No reboot type was specified in request")
        return {"type": node.getAttribute("type")}

    def _action_rebuild(self, node):
        rebuild = {}
        if node.hasAttribute("name"):
            rebuild['name'] = node.getAttribute("name")

        metadata_node = self.find_first_child_named(node, "metadata")
        if metadata_node is not None:
            rebuild["metadata"] = self.extract_metadata(metadata_node)

        personality = self._extract_personality(node)
        if personality is not None:
            rebuild["personality"] = personality

        if not node.hasAttribute("imageRef"):
            raise AttributeError("No imageRef was specified in request")
        rebuild["imageRef"] = node.getAttribute("imageRef")

        return rebuild

    def _action_resize(self, node):
        if not node.hasAttribute("flavorRef"):
            raise AttributeError("No flavorRef was specified in request")
        return {"flavorRef": node.getAttribute("flavorRef")}

    def _action_confirm_resize(self, node):
        return None

    def _action_revert_resize(self, node):
        return None

    def _deserialize_image_action(self, node, allowed_attributes):
        data = {}
        for attribute in allowed_attributes:
            value = node.getAttribute(attribute)
            if value:
                data[attribute] = value
        metadata_node = self.find_first_child_named(node, 'metadata')
        if metadata_node is not None:
            metadata = self.metadata_deserializer.extract_metadata(
                                                        metadata_node)
            data['metadata'] = metadata
        return data

    def create(self, string):
        """Deserialize an xml-formatted server create request"""
        dom = minidom.parseString(string)
        server = self._extract_server(dom)
        return {'body': {'server': server}}

    def _extract_server(self, node):
        """Marshal the server attribute of a parsed request"""
        server = {}
        server_node = self.find_first_child_named(node, 'server')

        attributes = ["name", "imageRef", "flavorRef", "adminPass",
                      "accessIPv4", "accessIPv6"]
        for attr in attributes:
            if server_node.getAttribute(attr):
                server[attr] = server_node.getAttribute(attr)

        metadata_node = self.find_first_child_named(server_node, "metadata")
        if metadata_node is not None:
            server["metadata"] = self.extract_metadata(metadata_node)

        personality = self._extract_personality(server_node)
        if personality is not None:
            server["personality"] = personality

        networks = self._extract_networks(server_node)
        if networks is not None:
            server["networks"] = networks

        security_groups = self._extract_security_groups(server_node)
        if security_groups is not None:
            server["security_groups"] = security_groups

        return server

    def _extract_personality(self, server_node):
        """Marshal the personality attribute of a parsed request"""
        node = self.find_first_child_named(server_node, "personality")
        if node is not None:
            personality = []
            for file_node in self.find_children_named(node, "file"):
                item = {}
                if file_node.hasAttribute("path"):
                    item["path"] = file_node.getAttribute("path")
                item["contents"] = self.extract_text(file_node)
                personality.append(item)
            return personality
        else:
            return None

    def _extract_networks(self, server_node):
        """Marshal the networks attribute of a parsed request"""
        node = self.find_first_child_named(server_node, "networks")
        if node is not None:
            networks = []
            for network_node in self.find_children_named(node,
                                                         "network"):
                item = {}
                if network_node.hasAttribute("uuid"):
                    item["uuid"] = network_node.getAttribute("uuid")
                if network_node.hasAttribute("fixed_ip"):
                    item["fixed_ip"] = network_node.getAttribute("fixed_ip")
                networks.append(item)
            return networks
        else:
            return None

    def _extract_security_groups(self, server_node):
        """Marshal the security_groups attribute of a parsed request"""
        node = self.find_first_child_named(server_node, "security_groups")
        if node is not None:
            security_groups = []
            for sg_node in self.find_children_named(node, "security_group"):
                item = {}
                name_node = self.find_first_child_named(sg_node, "name")
                if name_node:
                    item["name"] = self.extract_text(name_node)
                    security_groups.append(item)
            return security_groups
        else:
            return None


def create_resource(version='1.0'):
    controller = {
        '1.0': ControllerV10,
        '1.1': ControllerV11,
    }[version]()

    metadata = {
        "attributes": {
            "server": ["id", "imageId", "name", "flavorId", "hostId",
                       "status", "progress", "adminPass", "flavorRef",
                       "imageRef", "userId", "tenantId"],
            "link": ["rel", "type", "href"],
        },
        "dict_collections": {
            "metadata": {"item_name": "meta", "item_key": "key"},
        },
        "list_collections": {
            "public": {"item_name": "ip", "item_key": "addr"},
            "private": {"item_name": "ip", "item_key": "addr"},
        },
    }

    xmlns = {
        '1.0': wsgi.XMLNS_V10,
        '1.1': wsgi.XMLNS_V11,
    }[version]

    headers_serializer = HeadersSerializer()

    xml_serializer = {
        '1.0': wsgi.XMLDictSerializer(metadata, wsgi.XMLNS_V10),
        '1.1': ServerXMLSerializer(),
    }[version]

    body_serializers = {
        'application/xml': xml_serializer,
    }

    xml_deserializer = {
        '1.0': ServerXMLDeserializer(),
        '1.1': ServerXMLDeserializerV11(),
    }[version]

    body_deserializers = {
        'application/xml': xml_deserializer,
    }

    serializer = wsgi.ResponseSerializer(body_serializers, headers_serializer)
    deserializer = wsgi.RequestDeserializer(body_deserializers)

    return wsgi.Resource(controller, deserializer, serializer)


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context"""
    if FLAGS.allow_admin_api and context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
            if opt not in allowed_search_options]
    unk_opt_str = ", ".join(unknown_options)
    log_msg = _("Removing options '%(unk_opt_str)s' from query") % locals()
    LOG.debug(log_msg)
    for opt in unknown_options:
        search_options.pop(opt, None)
