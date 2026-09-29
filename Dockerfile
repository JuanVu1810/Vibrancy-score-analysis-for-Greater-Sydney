FROM python:3.11-slim

# Be patient with slow or flaky networks instead of hanging or failing on one bad connection
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=10

WORKDIR /work

# requirements.lock pins every package, so --no-deps skips the slow dependency resolution
COPY requirements.lock .
RUN pip install --no-cache-dir --no-deps -r requirements.lock

# The project itself is bind-mounted at /work by docker-compose.yml. There is no single default
# command: see README.md's "Run the analysis" section for the documented commands, each of which
# passes its own --entrypoint.
CMD ["bash", "-c", "echo 'No default command. See README.md, section \"Run the analysis\", for the documented commands.'; exit 1"]
