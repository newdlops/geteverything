FROM public.ecr.aws/lambda/python:3.12

RUN dnf update -y

# Install Chromium
COPY crawlers/fmkorea/install-browser.sh /tmp/
RUN /tmp/install-browser.sh
RUN dnf install -y nss libxcb net-tools
#RUN dnf install -y chromedriver

COPY crawlers/fmkorea/chrome-deps.txt /tmp/
#RUN dnf install libnss3 libxcb
RUN dnf install -y $(cat /tmp/chrome-deps.txt)
RUN dnf install -y tzdata \
 && ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime
# Install Python dependencies for function
COPY crawlers/fmkorea/requirements.txt /tmp/
RUN python3 -m pip install --upgrade pip -q
#RUN python3 -m pip install psycopg[binary]
RUN python3 -m pip install -r /tmp/requirements.txt -q
#RUN python3 -m pip uninstall -r dataclasses -q
RUN python3 -m pip uninstall -y typing dataclasses
#COPY --from=stage /opt/chrome /opt/chrome
#COPY --from=stage /opt/chromedriver /opt/chromedriver

# copy main.py
COPY crawlers/fmkorea/ /var/task/
COPY gadmin/ /var/task

ENV DATABASE_HOST "getev3.ctckuw2w4u3n.ap-northeast-2.rds.amazonaws.com"
ENV DATABASE_NAME "geteverything"
ENV DATABASE_PASSWORD "Dkyscd908070"
ENV DATABASE_PORT "5432"
ENV DATABASE_USER "getev"
ENV TZ="Asia/Seoul"

WORKDIR /var/task

CMD [ "app.lambda_handler" ]
