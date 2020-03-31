FROM ubuntu:18.04

RUN apt-get update -y && \
    apt-get install -y python3-dev python3-pip libffi-dev

RUN pip3 install --upgrade pip

RUN pip3 install python-magic flask_mail flask_openid werkzeug pymysql launchpadlib apscheduler

WORKDIR /app

COPY app/ /app/

RUN pip3 install -r requirements.txt

EXPOSE 5000:5000

CMD ["python3", "app.py"]
