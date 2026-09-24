"""Block until PostgreSQL accepts connections using environment or file credentials."""
import json
import os
import sys
import time

import psycopg2

TIMEOUT_SECONDS = 90

if os.environ.get("DB_PASSWORD"):
    cred = {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ.get("DB_NAME", os.environ.get("DB_USER", "postgres")),
    }
    credential_source = "database environment variables"
else:
    credentials_file = os.environ.get("CREDENTIALS_FILE", "Credentials.json")
    with open(credentials_file, encoding="utf-8") as f:
        cred = json.load(f)
    credential_source = credentials_file

dsn = dict(host=cred["host"], port=cred["port"], user=cred["user"],
           password=cred["password"], dbname=cred.get("database", cred["user"]),
           connect_timeout=3)

deadline = time.time() + TIMEOUT_SECONDS
while True:
    try:
        psycopg2.connect(**dsn).close()
        print(f"Database reachable at {cred['host']}:{cred['port']}")
        break
    except psycopg2.OperationalError as e:
        if time.time() > deadline:
            sys.exit(f"Could not connect to the database within {TIMEOUT_SECONDS}s "
                     f"({credential_source}: {cred['host']}:{cred['port']}):\n{e}")
        time.sleep(2)
