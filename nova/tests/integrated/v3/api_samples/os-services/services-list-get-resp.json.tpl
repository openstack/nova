{
    "services": [
        {
            "binary": "nova-scheduler",
            "disabled_reason": "test1",
            "host": "host1",
            "id": 1,
            "state": "up",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "disabled_reason": "test2",
            "host": "host1",
            "id": 2,
            "state": "up",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "nova"
        },
        {
            "binary": "nova-scheduler",
            "disabled_reason": null,
            "host": "host2",
            "id": 3,
            "state": "down",
            "status": "enabled",
            "updated_at": "%(strtime)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "disabled_reason": "test4",
            "host": "host2",
            "id": 4,
            "state": "down",
            "status": "disabled",
            "updated_at": "%(strtime)s",
            "zone": "nova"
        }
    ]
}
