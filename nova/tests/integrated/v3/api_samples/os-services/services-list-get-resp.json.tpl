{
    "services": [
        {
            "binary": "nova-scheduler",
            "disabled_reason": "test1",
            "host": "host1",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(timestamp)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "disabled_reason": "test2",
            "host": "host1",
            "state": "up",
            "status": "disabled",
            "updated_at": "%(timestamp)s",
            "zone": "nova"
        },
        {
            "binary": "nova-scheduler",
            "disabled_reason": "",
            "host": "host2",
            "state": "down",
            "status": "enabled",
            "updated_at": "%(timestamp)s",
            "zone": "internal"
        },
        {
            "binary": "nova-compute",
            "disabled_reason": "test4",
            "host": "host2",
            "state": "down",
            "status": "disabled",
            "updated_at": "%(timestamp)s",
            "zone": "nova"
        }
    ]
}
