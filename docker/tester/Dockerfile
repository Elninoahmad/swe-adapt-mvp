FROM python:3.11-slim

# Install only the test dependencies needed inside the container.
COPY tasks/task_01_extract_and_type/requirements-acceptance.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy the smoke-test suite into the image.
COPY docker/tester/smoke/test_isolation.py /smoke/test_isolation.py

WORKDIR /smoke
CMD ["pytest", "/smoke", "-v"]
