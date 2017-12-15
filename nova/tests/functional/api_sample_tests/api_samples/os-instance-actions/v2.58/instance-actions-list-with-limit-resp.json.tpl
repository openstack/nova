{
    "instanceActions": [
        {
            "action": "stop",
            "instance_uuid": "%(uuid)s",
            "request_id": "%(request_id)s",
            "user_id": "%(user_id)s",
            "project_id": "%(project_id)s",
            "start_time": "%(strtime)s",
            "updated_at": "%(strtime)s",
            "message": ""
        }
    ],
    "links": [
        {
            "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s/os-instance-actions?limit=1&marker=%(request_id)s",
            "rel": "next"
        }
    ]
}
