echo "Downloading Chromium..."
dnf install -y unzip

curl "https://storage.googleapis.com/chrome-for-testing-public/138.0.7204.49/linux64/chrome-linux64.zip" > /tmp/chrome-linux64.zip
unzip /tmp/chrome-linux64.zip -d /tmp/
mv /tmp/chrome-linux64/ /opt/chrome

#curl "https://storage.googleapis.com/chrome-for-testing-public/131.0.6778.108/linux64/chrome-headless-shell-linux64.zip" > /tmp/chrome-headless-shell-linux64.zip
#unzip /tmp/chrome-headless-shell-linux64.zip -d /tmp/
#mv /tmp/chrome-headless-shell-linux64/ /opt/chrome

curl "https://storage.googleapis.com/chrome-for-testing-public/138.0.7204.49/linux64/chromedriver-linux64.zip" > /tmp/chromedriver-linux64.zip
unzip /tmp/chromedriver-linux64.zip -d /tmp/
mv /tmp/chromedriver-linux64/chromedriver /opt/chromedriver
chmod 777 /opt/chrome
chmod 777 /opt/chromedriver
