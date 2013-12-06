{
    "limits": {
        "rate": [
            {
                "limit": [
                    {
                        "next-available": "%(timestamp)s",
                        "remaining": 10,
                        "unit": "MINUTE",
                        "value": 10,
                        "verb": "POST"
                    },
                    {
                        "next-available": "%(timestamp)s",
                        "remaining": 10,
                        "unit": "MINUTE",
                        "value": 10,
                        "verb": "PUT"
                    },
                    {
                        "next-available": "%(timestamp)s",
                        "remaining": 100,
                        "unit": "MINUTE",
                        "value": 100,
                        "verb": "DELETE"
                    }
                ],
                "regex": ".*",
                "uri": "*"
            },
            {
                "limit": [
                    {
                        "next-available": "%(timestamp)s",
                        "remaining": 50,
                        "unit": "DAY",
                        "value": 50,
                        "verb": "POST"
                    }
                ],
                "regex": "^/servers",
                "uri": "*/servers"
            },
            {
                "limit": [
                    {
                        "next-available": "%(timestamp)s",
                        "remaining": 3,
                        "unit": "MINUTE",
                        "value": 3,
                        "verb": "GET"
                    }
                ],
                "regex": ".*changes_since.*",
                "uri": "*changes_since*"
            }
        ]
    }
}
