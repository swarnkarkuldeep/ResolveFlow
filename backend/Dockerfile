FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .
COPY alembic.ini entrypoint.sh ./
COPY alembic ./alembic
RUN chmod +x entrypoint.sh && useradd --create-home app
USER app
ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]
