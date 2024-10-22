import json

# import requests

import os
import crawler

def lambda_handler(event, context):
    """
    """

    # try:
    #     ip = requests.get("http://checkip.amazonaws.com/")
    # except requests.RequestException as e:
    #     # Send some context about this error to Lambda Logs
    #     print(e)

    #     raise e
    crawler.crawl()


    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "success"
        }),
    }
