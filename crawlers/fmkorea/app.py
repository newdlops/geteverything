import json
import os
# import requests
if __name__ == 'app':
    from crawler import crawl
    from crawler import crawlertest
else:
    from .crawler import crawl
    from .crawler import crawlertest

def lambda_handler(event, context):
    """
    """

    # try:
    #     ip = requests.get("http://checkip.amazonaws.com/")
    # except requests.RequestException as e:
    #     # Send some context about this error to Lambda Logs
    #     print(e)

    #     raise e
    print("데이터베이스 설정 : " + os.getenv('DATABASE_HOST', 'None'))

    crawl()
    # crawlertest.crawl_example()

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "success"
        }),
    }
