# The client side of the compatibility suite: the real AWX 24.6.1 clients,
# unmodified, exactly as a stranded AWX user would have them.
#
# Python 3.11, not 3.12: awxkit 24.6.1 calls the private argparse API
# _parse_known_args(), whose signature changed in later 3.12 patch releases,
# and imports pkg_resources, which setuptools 81 removed. Both are awxkit's
# own rot -- AWX has had no release since 24.6.1 (2 July 2024) to fix them --
# and neither says anything about Forail. Pinning around them is what a user
# on a current distro has to do anyway.
FROM python:3.11-slim

RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends jq curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
      "setuptools<81" \
      awxkit==24.6.1 \
      ansible-core==2.17.6

RUN ansible-galaxy collection install awx.awx:24.6.1

COPY awxkit_suite.sh /suite/awxkit_suite.sh
COPY collection_suite.yml /suite/collection_suite.yml
WORKDIR /suite
