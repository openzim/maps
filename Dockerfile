FROM node:24-alpine AS zimui

WORKDIR /src
COPY zimui /src
RUN yarn install --frozen-lockfile
RUN yarn build

FROM python:3.14-bookworm
LABEL org.opencontainers.image.source=https://github.com/openzim/maps

# Install necessary packages
RUN python -m pip install --no-cache-dir -U \
     pip

RUN mkdir -p /output
WORKDIR /output

# Copy pyproject.toml and its dependencies
COPY README.md /src/
COPY scraper/pyproject.toml /src/scraper/
COPY scraper/src/maps2zim/__about__.py /src/scraper/src/maps2zim/__about__.py

# Install Python dependencies
RUN pip install --no-cache-dir /src/scraper

# Copy code + associated artifacts
COPY scraper/src /src/scraper/src
COPY *.md LICENSE /src/

# Install + cleanup
RUN pip install --no-cache-dir /src/scraper \
 && rm -rf /src/scraper

# Copy zimui build output
COPY --from=zimui /src/dist /src/zimui

ENV MAPS_ZIMUI_DIST=/src/zimui \
    MAPS_OUTPUT=/output \
    MAPS_TMP=/tmp\
    MAPS_CONTACT_INFO=https://www.kiwix.org

CMD ["maps2zim", "--help"]
