# check=skip=InvalidDefaultArgInFrom
# CADDY_VERSION is required; supported builds pass it from versions.env.
ARG CADDY_VERSION
FROM caddy:${CADDY_VERSION}-builder-alpine AS builder

ARG CADDY_VERSION
ARG FORWARDPROXY_COMMIT
# Follow forwardproxy's upstream build: QUIC BBR and authenticated CONNECT's
# idle-timeout override require these patches from the same pinned revision.
RUN git clone --depth 1 --branch "v${CADDY_VERSION}" https://github.com/caddyserver/caddy.git /src/caddy && \
    git init /src/forwardproxy && \
    git -C /src/forwardproxy remote add origin https://github.com/klzgrad/forwardproxy.git && \
    git -C /src/forwardproxy fetch --depth 1 origin "${FORWARDPROXY_COMMIT}" && \
    git -C /src/forwardproxy checkout --detach FETCH_HEAD && \
    git -C /src/caddy apply /src/forwardproxy/caddy-sing-quic-bbrv1.patch \
        /src/forwardproxy/caddy-read-idle-timeout.patch && \
    xcaddy build "v${CADDY_VERSION}" \
      --replace github.com/caddyserver/caddy/v2=/src/caddy \
      --with github.com/caddyserver/forwardproxy=/src/forwardproxy

FROM caddy:${CADDY_VERSION}-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy

