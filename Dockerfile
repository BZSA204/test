FROM python:3.10.6-alpine

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY  scripttest.py /app

ENTRYPOINT [ "python", "testarduino.py" ]