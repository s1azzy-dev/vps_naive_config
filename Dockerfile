# check=skip=InvalidDefaultArgInFrom
# CADDY_VERSION is required; supported builds pass it from versions.env.
ARG CADDY_VERSION
FROM caddy:${CADDY_VERSION}-builder-alpine AS builder

ARG CADDY_VERSION
ARG FORWARDPROXY_COMMIT
RUN test -n "${FORWARDPROXY_COMMIT}" && \
    xcaddy build "v${CADDY_VERSION}" \
      --with "github.com/caddyserver/forwardproxy=github.com/klzgrad/forwardproxy@${FORWARDPROXY_COMMIT}"

FROM caddy:${CADDY_VERSION}-alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy

