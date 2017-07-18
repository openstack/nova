{
    "services": [
        {
            "binary": "nova-scheduler",
            "disabled_reason": "test1",
            "forced_down": false,
            "host": "host1",
            "id": "%(id)s",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "disabled_reason": "test2",
            "forced_down": false,
            "host": "host1",
            "id": "%(id)s",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "nova"
        },
        {
            "binary": "nova-scheduler",
            "disabled_reason": null,
            "forced_down": false,
            "host": "host2",
            "id": "%(id)s",
            "state": "down",
            "status": "enabled",
            "updated_at": "%(strtime)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "disabled_reason": "test4",
            "forced_down": false,
            "host": "host2",
            "id": "%(id)s",
            "state": "down",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "nova"
        }
    ]
}
