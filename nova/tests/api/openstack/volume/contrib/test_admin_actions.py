import webob

from nova import context
from nova import db
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes


def app():
    # no auth, just let environ['nova.context'] pass through
    api = fakes.volume.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v1'] = api
    return mapper


class AdminActionsTest(test.TestCase):

    def test_reset_status_as_admin(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available'})
        req = webob.Request.blank('/v1/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-reset_status': {'status': 'error'}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEquals(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # status changed to 'error'
        self.assertEquals(volume['status'], 'error')

    def test_reset_status_as_non_admin(self):
        # current status is 'error'
        volume = db.volume_create(context.get_admin_context(),
                                  {'status': 'error'})
        req = webob.Request.blank('/v1/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request changing status to available
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'available'}})
        # non-admin context
        req.environ['nova.context'] = context.RequestContext('fake', 'fake')
        resp = req.get_response(app())
        # request is not authorized
        self.assertEquals(resp.status_int, 403)
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        # status is still 'error'
        self.assertEquals(volume['status'], 'error')

    def test_malformed_reset_status_body(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available'})
        req = webob.Request.blank('/v1/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # malformed request body
        req.body = jsonutils.dumps({'os-reset_status': {'x-status': 'bad'}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # bad request
        self.assertEquals(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status is still 'available'
        self.assertEquals(volume['status'], 'available')

    def test_invalid_status_for_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available'})
        req = webob.Request.blank('/v1/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # 'invalid' is not a valid status
        req.body = jsonutils.dumps({'os-reset_status': {'status': 'invalid'}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # bad request
        self.assertEquals(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status is still 'available'
        self.assertEquals(volume['status'], 'available')

    def test_reset_status_for_missing_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # missing-volume-id
        req = webob.Request.blank('/v1/fake/volumes/%s/action' %
                                  'missing-volume-id')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # malformed request body
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'available'}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # not found
        self.assertEquals(resp.status_int, 404)
        self.assertRaises(exception.NotFound, db.volume_get, ctx,
                          'missing-volume-id')

    def test_snapshot_reset_status(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # snapshot in 'error_deleting'
        volume = db.volume_create(ctx, {})
        snapshot = db.snapshot_create(ctx, {'status': 'error_deleting',
                                            'volume_id': volume['id']})
        req = webob.Request.blank('/v1/fake/snapshots/%s/action' %
                                  snapshot['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-reset_status': {'status': 'error'}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEquals(resp.status_int, 202)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        # status changed to 'error'
        self.assertEquals(snapshot['status'], 'error')

    def test_invalid_status_for_snapshot(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # snapshot in 'available'
        volume = db.volume_create(ctx, {})
        snapshot = db.snapshot_create(ctx, {'status': 'available',
                                            'volume_id': volume['id']})
        req = webob.Request.blank('/v1/fake/snapshots/%s/action' %
                                  snapshot['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # 'attaching' is not a valid status for snapshots
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'attaching'}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        print resp
        self.assertEquals(resp.status_int, 400)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        # status is still 'available'
        self.assertEquals(snapshot['status'], 'available')

    def test_force_delete(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        ctx.elevated()  # add roles
        # current status is creating
        volume = db.volume_create(ctx, {'status': 'creating'})
        req = webob.Request.blank('/v1/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dumps({'os-force_delete': {}})
        # attach admin context to request
        req.environ['nova.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEquals(resp.status_int, 202)
        # volume is deleted
        self.assertRaises(exception.NotFound, db.volume_get, ctx, volume['id'])
