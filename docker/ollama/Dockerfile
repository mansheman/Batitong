# =============================================================================
# Ollama init container — pulls the configured models against the long-lived
# `ollama` service. Tiny image; just curl + sh.
# =============================================================================

FROM alpine:3.20

RUN apk add --no-cache curl bash

COPY docker/ollama/pull-models.sh /usr/local/bin/pull-models.sh
RUN chmod +x /usr/local/bin/pull-models.sh

CMD ["/usr/local/bin/pull-models.sh"]
