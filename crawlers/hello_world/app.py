import os, shutil, uuid, json

from selenium import  webdriver
from selenium.webdriver.chrome.service import Service
# import chromedriver_binary


# import requests

def setup():
    BIN_DIR = "/tmp/bin"
    if not os.path.exists(BIN_DIR):
        print("Creating bin folder")
        os.makedirs(BIN_DIR)

    LIB_DIR = '/tmp/bin/lib'
    if not os.path.exists(LIB_DIR):
        print("Creating lib folder")
        os.makedirs(LIB_DIR)

    for filename in ['chromedriver', 'headless-chromium', 'lib/libgconf-2.so.4', 'lib/libORBit-2.so.0']:
        oldfile = f'/opt/{filename}'
        newfile = f'{BIN_DIR}/{filename}'
        shutil.copy2(oldfile, newfile)
        os.chmod(newfile, 0o775)

def init_web_driver():
    # setup()
    chrome_options = webdriver.ChromeOptions()
    _tmp_folder = '/tmp/{}'.format(uuid.uuid4())

    if not os.path.exists(_tmp_folder):
        os.makedirs(_tmp_folder)

    if not os.path.exists(_tmp_folder + '/user-data'):
        os.makedirs(_tmp_folder + '/user-data')

    if not os.path.exists(_tmp_folder + '/data-path'):
        os.makedirs(_tmp_folder + '/data-path')

    if not os.path.exists(_tmp_folder + '/cache-dir'):
        os.makedirs(_tmp_folder + '/cache-dir')

    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1280x1696')
    chrome_options.add_argument('--user-data-dir={}'.format(_tmp_folder + '/user-data'))
    chrome_options.add_argument('--hide-scrollbars')
    chrome_options.add_argument('--enable-logging')
    chrome_options.add_argument('--log-level=0')
    chrome_options.add_argument('--v=99')
    chrome_options.add_argument('--single-process')
    chrome_options.add_argument('--data-path={}'.format(_tmp_folder + '/data-path'))
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--homedir={}'.format(_tmp_folder))
    chrome_options.add_argument('--disk-cache-dir={}'.format(_tmp_folder + '/cache-dir'))
    chrome_options.add_argument(
        'user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36')

    chrome_options.binary_location = "/tmp/task/chromedriver_binary"

    driver = webdriver.Chrome(options=chrome_options)
    return driver


def lambda_handler(event, context):
    """Sample pure Lambda function

    Parameters
    ----------
    event: dict, required
        API Gateway Lambda Proxy Input Format

        Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format

    context: object, required
        Lambda Context runtime methods and attributes

        Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    ------
    API Gateway Lambda Proxy Output Format: dict

        Return doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
    """

    # try:
    #     ip = requests.get("http://checkip.amazonaws.com/")
    # except requests.RequestException as e:
    #     # Send some context about this error to Lambda Logs
    #     print(e)
    print("22222222222222")
    # chromedriver_binary.add_chromedriver_to_path()
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--single-process")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-dev-shm-using")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument('--dns-prefetch-disable')
    chrome_options.add_argument("start-maximized")
    chrome_options.add_argument("disable-infobars")
    chrome_options.add_argument(r"user-data-dir=.\cookies\\test")
    chrome_options.binary_location = '/opt/chrome/chrome'
    # chrome_options.binary_location = '/opt/chrome/chrome-headless-shell'
    # chrome_options.binary_location = '/opt/chromedriver'
    # print("크롬드라이버:"+chromedriver_binary.chromedriver_filename)
    service = Service(executable_path="/opt/chromedriver")
    # service = Service(executable_path="/opt/chrome/chrome-headless-shell")
    # service = Service(ChromeDriverManager().install())

    #     raise e
    # driver = init_web_driver()
    try:
        driver  = webdriver.Chrome(service=service, options=chrome_options)
        driver.get("http://www.python.org")
    except Exception as e:
        print("에러", e)
    print(driver.title)
    print("로그가 잘되는지 테스트")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "hello world",
            # "location": ip.text.replace("\n", "")
        }),
    }
