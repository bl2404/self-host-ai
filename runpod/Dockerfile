FROM ghcr.io/open-webui/open-webui:main

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends autossh openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY tunnel-entrypoint.sh /usr/local/bin/tunnel-entrypoint
RUN chmod 0755 /usr/local/bin/tunnel-entrypoint

ENTRYPOINT ["/usr/local/bin/tunnel-entrypoint"]
CMD ["bash", "start.sh"]
