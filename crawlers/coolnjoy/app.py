import json

# import requests
if __name__ == 'app':
    from crawler import crawl
else:
    from .crawler import crawl

def lambda_handler(event, context):
    """
    """

    # try:
    #     ip = requests.get("http://checkip.amazonaws.com/")
    # except requests.RequestException as e:
    #     # Send some context about this error to Lambda Logs
    #     print(e)

    #     raise e
    crawl()


    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "success"
        }),
    }
