FROM public.ecr.aws/lambda/python:3.12

RUN dnf update -y

# Install Chromium
COPY install-browser.sh /tmp/
RUN /tmp/install-browser.sh
RUN dnf install -y nss libxcb

#RUN dnf install -y chromedriver

COPY chrome-deps.txt /tmp/
#RUN dnf install libnss3 libxcb
RUN dnf install -y $(cat /tmp/chrome-deps.txt)

# Install Python dependencies for function
COPY requirements.txt /tmp/
RUN python3 -m pip install --upgrade pip -q
RUN python3 -m pip install -r /tmp/requirements.txt -q

#COPY --from=stage /opt/chrome /opt/chrome
#COPY --from=stage /opt/chromedriver /opt/chromedriver

# copy main.py
COPY app.py /var/task/


WORKDIR /var/task

CMD [ "app.lambda_handler" ]
