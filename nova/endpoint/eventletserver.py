import eventlet
import eventlet.wsgi
eventlet.patcher.monkey_patch(all=False, socket=True)

def serve(app, port):
    sock = eventlet.listen(('0.0.0.0', port))
    eventlet.wsgi.server(sock, app)
